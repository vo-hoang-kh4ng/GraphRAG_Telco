"""Reproducibly fetch + parse the DejaVu "A1" real-world fault dataset and
regenerate src/kg/dejavu_data.py from it.

Source: NetManAIOps/DejaVu (ESEC/FSE'22, Li et al., Tsinghua), hosted on
Zenodo: https://zenodo.org/records/6955909 (DOI 10.5281/zenodo.6955909),
license CC-BY 4.0. This is REAL microservice/infra fault data (not telecom),
used here as a real-data cross-domain check for the same KG + rule engine +
GraphRAG pipeline built for the telecom scenarios -- see README.md for why
(NetRCA's infra was dead, TeleLogs is gated + non-redistributable, DejaVu is
neither).

Usage:
    python scripts/fetch_dejavu.py

Downloads A1.zip once into scripts/.cache/, parses graph.yml (topology) and
faults.csv (real incidents with ground-truth root cause), and overwrites
src/kg/dejavu_data.py. Safe to re-run; the cached zip is reused if present.
"""

import csv
import io
import re
from datetime import datetime, timezone
import urllib.request
import zipfile
from pathlib import Path

import yaml

DEJAVU_URL = "https://zenodo.org/records/6955909/files/A1.zip?download=1"
CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_ZIP = CACHE_DIR / "dejavu_A1.zip"
OUTPUT_FILE = Path(__file__).parent.parent / "src" / "kg" / "dejavu_data.py"

FAULT_TYPE_MAP = {
    "CPU fault": "CPU_FAULT",
    "network delay": "NETWORK_DELAY",
    "network loss": "NETWORK_LOSS",
    "db connection limit": "DB_CONNECTION_LIMIT",
    "db  close": "DB_CLOSE",
    "db close": "DB_CLOSE",
}

# Plain-language Vietnamese gloss for each raw fault_description value, so the
# demo UI doesn't show untranslated technical jargon straight from the CSV.
FAULT_TYPE_VI = {
    "CPU fault": "quá tải CPU",
    "network delay": "độ trễ mạng cao bất thường",
    "network loss": "mất gói tin trên mạng",
    "db connection limit": "vượt giới hạn số kết nối database",
    "db  close": "mất kết nối / đóng phiên database",
    "db close": "mất kết nối / đóng phiên database",
}

DEVICE_CATEGORY_VI = {
    "docker": "container",
    "db": "database",
    "os": "máy chủ vật lý (host)",
    "osb": "gateway dịch vụ (Online Service Bus)",
}


def device_category_vi(device_id):
    prefix = device_id.split("_")[0]
    return DEVICE_CATEGORY_VI.get(prefix, "thiết bị")


def download_zip():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_ZIP.exists():
        return CACHE_ZIP.read_bytes()
    print(f"Downloading {DEJAVU_URL} ...")
    with urllib.request.urlopen(DEJAVU_URL) as resp:
        data = resp.read()
    CACHE_ZIP.write_bytes(data)
    return data


def load_raw_files(zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        graph_yml = zf.read("A1/graph.yml").decode("utf-8")
        faults_csv = zf.read("A1/faults.csv").decode("utf-8")
    return graph_yml, faults_csv


def parse_topology(graph_yml_text):
    """Return DEVICES: list of {"id","name","type","depends_on":[parent_ids]}.

    Node ids come from `graph.yml`'s node-block params (docker_XXX/db_XXX/
    os_XXX). Edges come from the "call" blocks (service dependency: src
    depends on dst) and the "deployment" blocks with docker/os keys (a
    container depends on the host it runs on). Both map onto our
    child-DEPENDS_ON->parent relation directly.
    """
    docs = yaml.safe_load(graph_yml_text)
    node_blocks = [d for d in docs if d.get("class") == "node"]
    edge_blocks = [d for d in docs if d.get("class") == "edge"]

    all_ids = set()
    id_type = {}
    for n in node_blocks:
        params = n["params"]
        key = next(iter(params))
        node_type = n["type"]
        # Only the base "object" node types correspond to real devices in
        # faults.csv (docker/db/os/osb); "OS Network"/"Docker CPU"/etc are
        # metric-group sub-nodes of the same underlying object, not separate
        # devices, so they're skipped here.
        if node_type not in {"Docker", "DB", "OS", "OSB"}:
            continue
        for v in params[key]:
            all_ids.add(v)
            id_type[v] = node_type.lower()

    depends_on = {i: set() for i in all_ids}
    for e in edge_blocks:
        params = e["params"]
        if e.get("type") == "call" and set(params.keys()) == {"src", "dst"}:
            for s, d in zip(params["src"], params["dst"]):
                if s in depends_on and d in all_ids:
                    depends_on[s].add(d)
        elif e.get("type") == "deployment" and set(params.keys()) == {"docker", "os"}:
            for dk, osv in zip(params["docker"], params["os"]):
                if dk in depends_on and osv in all_ids:
                    depends_on[dk].add(osv)

    devices = []
    for dev_id in sorted(all_ids):
        devices.append(
            {
                "id": dev_id,
                "name": dev_id,
                "type": id_type[dev_id],
                "depends_on": sorted(depends_on[dev_id]),
            }
        )
    return devices


def parse_incidents(faults_csv_text):
    """Return INCIDENTS: list matching the SCENARIOS shape consumed by
    src.kg.graph_builder.load_scenario() -- id/name/description/alarms/
    kpi_anomalies/ground_truth_root_cause.

    `name`/`description` are written in plain Vietnamese (not the raw CSV
    jargon like "db  close") so the demo UI is understandable without
    IT-ops background knowledge -- see README "Dữ liệu thật" section.
    """
    reader = csv.DictReader(io.StringIO(faults_csv_text))
    incidents = []
    for idx, row in enumerate(reader, start=1):
        device_id = row["name"]
        fault_desc = row["fault_description"]
        fault_vi = FAULT_TYPE_VI.get(fault_desc, fault_desc.strip())
        category = device_category_vi(device_id)
        alarm_type = FAULT_TYPE_MAP.get(fault_desc, re.sub(r"\W+", "_", fault_desc.strip()).upper())
        incident_id = f"DEJAVU-{idx:03d}"
        readable_time = datetime.fromtimestamp(int(row["timestamp"]), tz=timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
        incidents.append(
            {
                "id": incident_id,
                "name": f"Sự cố #{idx}: {fault_vi} tại {device_id} ({category})",
                "description": (
                    f"Sự cố thật #{idx} (dataset DejaVu): thiết bị {device_id} ({category}) gặp "
                    f"'{fault_vi}' (mã gốc trong dữ liệu: \"{fault_desc.strip()}\"). Ghi nhận lúc "
                    f"{readable_time}. Nguyên nhân gốc rễ (ground truth): {device_id}."
                ),
                "alarms": [{"device": device_id, "type": alarm_type, "severity": "major"}],
                "kpi_anomalies": [],
                "ground_truth_root_cause": device_id,
            }
        )
    return incidents


def render_module(devices, incidents):
    header = '''"""Real fault-diagnosis data from NetManAIOps/DejaVu (ESEC/FSE'22, Li et al.,
Tsinghua) -- used as a real-data, cross-domain check for the KG + rule engine
+ GraphRAG pipeline built for the (synthetic) telecom scenarios.

Source: https://zenodo.org/records/6955909 (DOI 10.5281/zenodo.6955909),
license CC-BY 4.0 -- redistribution of this derived subset is permitted with
attribution, unlike the other real datasets considered (see README.md for
the full data-sourcing story: NetRCA's challenge infra was dead, TeleLogs is
gated + explicitly non-redistributable).

IMPORTANT CAVEAT: this is real microservice/infrastructure fault data
(Docker containers, DB instances, OS hosts calling each other), NOT telecom
network data. It is used here because its structure -- a real dependency
DAG with real fault injection and real ground-truth root-cause labels -- is
the same graph-theoretic shape (dependency graph + fault propagation + root
cause localization) as the telecom cascade problem this project targets, so
it is a legitimate generalization check, not a telecom dataset.

All incidents in this dataset are single-device, non-cascading faults
(root cause is always the same device that shows the fault) -- i.e. they
exercise the "isolated device fault" rule / structural-diagnosis path on a
messy real multi-parent DAG (unlike the synthetic telecom scenarios, which
specifically also test cascading multi-device attribution).

Regenerate with: python scripts/fetch_dejavu.py -- do not hand-edit.
"""

'''
    devices_repr = "DEVICES = [\n"
    for d in devices:
        devices_repr += (
            f'    {{"id": {d["id"]!r}, "type": {d["type"]!r}, "name": {d["name"]!r}, '
            f'"depends_on": {d["depends_on"]!r}}},\n'
        )
    devices_repr += "]\n\n"

    incidents_repr = "INCIDENTS = [\n"
    for inc in incidents:
        incidents_repr += "    {\n"
        incidents_repr += f'        "id": {inc["id"]!r},\n'
        incidents_repr += f'        "name": {inc["name"]!r},\n'
        incidents_repr += f'        "description": {inc["description"]!r},\n'
        incidents_repr += f'        "alarms": {inc["alarms"]!r},\n'
        incidents_repr += '        "kpi_anomalies": [],\n'
        incidents_repr += f'        "ground_truth_root_cause": {inc["ground_truth_root_cause"]!r},\n'
        incidents_repr += "    },\n"
    incidents_repr += "]\n"

    return header + devices_repr + incidents_repr


def main():
    zip_bytes = download_zip()
    graph_yml_text, faults_csv_text = load_raw_files(zip_bytes)
    devices = parse_topology(graph_yml_text)
    incidents = parse_incidents(faults_csv_text)
    module_src = render_module(devices, incidents)
    OUTPUT_FILE.write_text(module_src, encoding="utf-8")
    print(f"Wrote {OUTPUT_FILE} -- {len(devices)} devices, {len(incidents)} real incidents.")


if __name__ == "__main__":
    main()
