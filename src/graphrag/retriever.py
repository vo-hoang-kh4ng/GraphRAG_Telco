"""Subgraph retrieval for GraphRAG (section 5.2, step 1-2).

Given an active incident, identify the seed entities (devices with an alarm
or KPI anomaly attached to that incident), then pull a bounded multi-hop
neighbourhood around them from Neo4j -- topology, alarms, KPIs, affected
services and any historical incidents tied to a device in that neighbourhood.
"""

from src.kg import schema

DEFAULT_HOPS = 2


def _seed_devices(conn, incident_id):
    # NOTE: dedup is done in Python, not via Cypher DISTINCT/collect(DISTINCT ..) --
    # those were observed to NOT collapse duplicate rows produced by the two
    # OPTIONAL MATCH branches on this Neo4j version, even on a plain scalar
    # projection (verified directly in cypher-shell).
    alarm_rows = conn.run(
        f"""
        MATCH (i:{schema.LABEL_INCIDENT} {{id: $incident_id}})
        MATCH (d:{schema.LABEL_DEVICE})-[:{schema.REL_RAISED_ALARM}]->(:{schema.LABEL_ALARM})
            -[:{schema.REL_PART_OF_INCIDENT}]->(i)
        RETURN d.id AS device_id
        """,
        {"incident_id": incident_id},
    )
    kpi_rows = conn.run(
        f"""
        MATCH (i:{schema.LABEL_INCIDENT} {{id: $incident_id}})
        MATCH (d:{schema.LABEL_DEVICE})-[:{schema.REL_HAS_KPI}]->(:{schema.LABEL_KPI})
            -[:{schema.REL_PART_OF_INCIDENT}]->(i)
        RETURN d.id AS device_id
        """,
        {"incident_id": incident_id},
    )
    seed_ids = {r["device_id"] for r in alarm_rows} | {r["device_id"] for r in kpi_rows}
    return sorted(seed_ids)


def retrieve_subgraph(conn, incident_id, hops=DEFAULT_HOPS):
    """Return a structured dict describing the neighbourhood relevant to `incident_id`."""

    seed_ids = _seed_devices(conn, incident_id)
    if not seed_ids:
        return {
            "incident_id": incident_id,
            "seed_devices": [],
            "devices": [],
            "alarms": [],
            "kpis": [],
            "services": [],
            "historical_incidents": [],
        }

    # Same dedup caveat as _seed_devices: collapse duplicate (seed, neighbor)
    # rows in Python rather than relying on Cypher DISTINCT here. A neighbor
    # may also have more than one DEPENDS_ON parent (DAG, not a tree), so
    # parent ids are collected into a list per device instead of overwritten.
    device_rows = conn.run(
        f"""
        MATCH (seed:{schema.LABEL_DEVICE}) WHERE seed.id IN $seed_ids
        MATCH (seed)-[:{schema.REL_DEPENDS_ON}*0..{hops}]-(neighbor:{schema.LABEL_DEVICE})
        OPTIONAL MATCH (neighbor)-[:{schema.REL_DEPENDS_ON}]->(parent:{schema.LABEL_DEVICE})
        OPTIONAL MATCH (neighbor)-[:{schema.REL_BELONGS_TO_SITE}]->(site:{schema.LABEL_SITE})
        RETURN neighbor.id AS id, neighbor.type AS type, neighbor.name AS name,
               parent.id AS parent_id, site.name AS site_name
        """,
        {"seed_ids": seed_ids},
    )
    devices_by_id = {}
    for r in device_rows:
        d = devices_by_id.setdefault(
            r["id"], {"id": r["id"], "type": r["type"], "name": r["name"], "site_name": r["site_name"], "parent_ids": set()}
        )
        if r["parent_id"]:
            d["parent_ids"].add(r["parent_id"])
    devices = []
    for d in devices_by_id.values():
        d["parent_ids"] = sorted(d["parent_ids"])
        devices.append(d)
    device_ids = [d["id"] for d in devices]

    alarm_rows = conn.run(
        f"""
        MATCH (d:{schema.LABEL_DEVICE})-[:{schema.REL_RAISED_ALARM}]->(a:{schema.LABEL_ALARM})
        WHERE d.id IN $device_ids
        RETURN d.id AS device_id, a.type AS type, a.severity AS severity
        """,
        {"device_ids": device_ids},
    )
    alarms = [dict(r) for r in alarm_rows]

    kpi_rows = conn.run(
        f"""
        MATCH (d:{schema.LABEL_DEVICE})-[:{schema.REL_HAS_KPI}]->(k:{schema.LABEL_KPI})
        WHERE d.id IN $device_ids
        RETURN d.id AS device_id, k.name AS name, k.value AS value, k.status AS status
        """,
        {"device_ids": device_ids},
    )
    kpis = [dict(r) for r in kpi_rows]

    service_rows = conn.run(
        f"""
        MATCH (d:{schema.LABEL_DEVICE})-[:{schema.REL_AFFECTS_SERVICE}]->(s:{schema.LABEL_SERVICE})
        WHERE d.id IN $device_ids
        RETURN d.id AS device_id, s.name AS service_name
        """,
        {"device_ids": device_ids},
    )
    services = [dict(r) for r in service_rows]

    history_rows = conn.run(
        f"""
        MATCH (h:{schema.LABEL_INCIDENT} {{historical: true}})-[:{schema.REL_CAUSED_BY}]->(d:{schema.LABEL_DEVICE})
        WHERE d.id IN $device_ids
        RETURN h.id AS id, h.title AS title, h.summary AS summary, d.id AS root_cause_device
        """,
        {"device_ids": device_ids},
    )
    historical_incidents = [dict(r) for r in history_rows]

    return {
        "incident_id": incident_id,
        "seed_devices": seed_ids,
        "devices": devices,
        "alarms": alarms,
        "kpis": kpis,
        "services": services,
        "historical_incidents": historical_incidents,
    }
