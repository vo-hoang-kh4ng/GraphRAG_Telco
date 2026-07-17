"""Builds and refreshes the telecom Knowledge Graph inside Neo4j.

Two layers are loaded separately:
  * static topology (sites, devices, services, historical incidents) - loaded
    once and shared across scenarios;
  * scenario state (active alarms, KPI anomalies, current Incident node) -
    cleared and reloaded every time a new incident scenario is analysed.
"""

from src.kg import schema
from src.kg.sample_data import DEVICES, HISTORICAL_INCIDENTS, SERVICES, SITES


def reset_all(conn):
    conn.run_write("MATCH (n) DETACH DELETE n")


def build_constraints(conn):
    for label in schema.ALL_LABELS:
        conn.run_write(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")


def load_devices(conn, devices):
    """Load Device nodes and their DEPENDS_ON edges.

    `devices` items: {"id", "name", "type", "depends_on": [parent_id, ...]}.
    `depends_on` is a list because topology is a DAG, not necessarily a tree
    (e.g. a service that calls several backends and also depends on the host
    it runs on) -- an empty list means a root node with no upstream dependency.
    """
    conn.run_write(
        f"""
        UNWIND $devices AS d
        MERGE (dev:{schema.LABEL_DEVICE} {{id: d.id}})
        SET dev.name = d.name, dev.type = d.type
        """,
        {"devices": devices},
    )
    conn.run_write(
        f"""
        UNWIND $devices AS d
        MATCH (child:{schema.LABEL_DEVICE} {{id: d.id}})
        WITH child, d
        UNWIND d.depends_on AS parent_id
        MATCH (parent:{schema.LABEL_DEVICE} {{id: parent_id}})
        MERGE (child)-[:{schema.REL_DEPENDS_ON}]->(parent)
        MERGE (child)-[:{schema.REL_CONNECTS_TO}]->(parent)
        """,
        {"devices": devices},
    )


def load_sites(conn, sites):
    conn.run_write(
        f"""
        UNWIND $sites AS s
        MERGE (site:{schema.LABEL_SITE} {{id: s.id}})
        SET site.name = s.name, site.region = s.region
        """,
        {"sites": sites},
    )


def attach_devices_to_sites(conn, devices):
    conn.run_write(
        f"""
        UNWIND $devices AS d
        MATCH (dev:{schema.LABEL_DEVICE} {{id: d.id}})
        MATCH (site:{schema.LABEL_SITE} {{id: d.site}})
        MERGE (dev)-[:{schema.REL_BELONGS_TO_SITE}]->(site)
        """,
        {"devices": devices},
    )


def load_services(conn, services):
    conn.run_write(
        f"""
        UNWIND $services AS svc
        MERGE (s:{schema.LABEL_SERVICE} {{id: svc.id}})
        SET s.name = svc.name
        WITH s, svc
        UNWIND svc.affected_by AS dev_id
        MATCH (dev:{schema.LABEL_DEVICE} {{id: dev_id}})
        MERGE (dev)-[:{schema.REL_AFFECTS_SERVICE}]->(s)
        """,
        {"services": services},
    )


def load_historical_incidents(conn, incidents):
    conn.run_write(
        f"""
        UNWIND $incidents AS inc
        MERGE (i:{schema.LABEL_INCIDENT} {{id: inc.id}})
        SET i.title = inc.title, i.summary = inc.summary, i.historical = true
        WITH i, inc
        MATCH (dev:{schema.LABEL_DEVICE} {{id: inc.root_cause_device}})
        MERGE (i)-[:{schema.REL_CAUSED_BY}]->(dev)
        """,
        {"incidents": incidents},
    )


def load_static_topology(conn):
    """Load the telecom sites, devices (+ topology edges), services and
    historical incidents (src/kg/sample_data.py)."""
    load_sites(conn, SITES)
    load_devices(conn, DEVICES)
    attach_devices_to_sites(conn, DEVICES)
    load_services(conn, SERVICES)
    load_historical_incidents(conn, HISTORICAL_INCIDENTS)


def clear_scenario_state(conn):
    """Remove active Alarm/KPI/Incident nodes from a previous scenario run.

    Historical incidents (`historical: true`) are preserved so GraphRAG can
    still retrieve them as prior-case context.
    """
    conn.run_write(f"MATCH (a:{schema.LABEL_ALARM}) DETACH DELETE a")
    conn.run_write(f"MATCH (k:{schema.LABEL_KPI}) DETACH DELETE k")
    conn.run_write(
        f"MATCH (i:{schema.LABEL_INCIDENT}) WHERE i.historical IS NULL OR i.historical = false DETACH DELETE i"
    )


def load_scenario(conn, scenario):
    """Materialise a scenario's alarms/KPI anomalies as active KG state.

    Returns the id of the created Incident node.
    """
    clear_scenario_state(conn)

    incident_id = scenario["id"]
    conn.run_write(
        f"""
        CREATE (i:{schema.LABEL_INCIDENT} {{id: $id, title: $name, description: $description, historical: false}})
        """,
        {"id": incident_id, "name": scenario["name"], "description": scenario["description"]},
    )

    if scenario["alarms"]:
        conn.run_write(
            f"""
            UNWIND $alarms AS a
            MATCH (dev:{schema.LABEL_DEVICE} {{id: a.device}})
            MATCH (i:{schema.LABEL_INCIDENT} {{id: $incident_id}})
            CREATE (alarm:{schema.LABEL_ALARM} {{
                id: a.device + '-' + a.type,
                type: a.type,
                severity: a.severity
            }})
            MERGE (dev)-[:{schema.REL_RAISED_ALARM}]->(alarm)
            MERGE (alarm)-[:{schema.REL_PART_OF_INCIDENT}]->(i)
            """,
            {"alarms": scenario["alarms"], "incident_id": incident_id},
        )

    if scenario["kpi_anomalies"]:
        conn.run_write(
            f"""
            UNWIND $kpis AS k
            MATCH (dev:{schema.LABEL_DEVICE} {{id: k.device}})
            CREATE (kpi:{schema.LABEL_KPI} {{
                id: k.device + '-' + k.kpi,
                name: k.kpi,
                value: k.value,
                status: k.status
            }})
            MERGE (dev)-[:{schema.REL_HAS_KPI}]->(kpi)
            WITH kpi
            MATCH (i:{schema.LABEL_INCIDENT} {{id: $incident_id}})
            MERGE (kpi)-[:{schema.REL_PART_OF_INCIDENT}]->(i)
            """,
            {"kpis": scenario["kpi_anomalies"], "incident_id": incident_id},
        )

    return incident_id


def bootstrap(conn):
    """Convenience: wipe, build constraints, and load the telecom static topology."""
    reset_all(conn)
    build_constraints(conn)
    load_static_topology(conn)


def bootstrap_devices_only(conn, devices):
    """Wipe, build constraints, and load a bare Device/DEPENDS_ON topology --
    no Site/Service/historical-Incident layer. Used to run the same KG +
    rule engine + GraphRAG pipeline against a different topology/incident
    dataset (e.g. src/kg/dejavu_data.py) without touching telecom data.
    """
    reset_all(conn)
    build_constraints(conn)
    load_devices(conn, devices)
