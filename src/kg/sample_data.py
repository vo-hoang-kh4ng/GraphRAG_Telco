"""Sample telecom network data (topology, KPIs, historical incidents).

Scale and device types follow section 4 of the đề cương: a moderate simulated
topology covering transmission, router, OLT and gNodeB/BTS devices across two
sites, used as a prototype dataset (not real operational data).
"""

# --- Sites -------------------------------------------------------------------
SITES = [
    {"id": "SITE_A", "name": "Site A - Quan 1", "region": "HCMC"},
    {"id": "SITE_B", "name": "Site B - Cau Giay", "region": "Hanoi"},
]

# --- Devices -------------------------------------------------------------------
# `depends_on` encodes the physical/logical dependency chain used by the rule
# engine and GraphRAG retriever for multi-hop cause-effect reasoning.
DEVICES = [
    {"id": "TRANS-CORE-1", "type": "transmission", "name": "Core Transmission Node A", "site": "SITE_A", "depends_on": None},
    {"id": "RTR-EDGE-1", "type": "router", "name": "Edge Router A1", "site": "SITE_A", "depends_on": "TRANS-CORE-1"},
    {"id": "OLT-A1", "type": "olt", "name": "OLT A1", "site": "SITE_A", "depends_on": "RTR-EDGE-1"},
    {"id": "GNB-A1", "type": "gnodeb", "name": "gNodeB A1", "site": "SITE_A", "depends_on": "RTR-EDGE-1"},
    {"id": "GNB-A2", "type": "gnodeb", "name": "gNodeB A2", "site": "SITE_A", "depends_on": "RTR-EDGE-1"},
    {"id": "TRANS-CORE-2", "type": "transmission", "name": "Core Transmission Node B", "site": "SITE_B", "depends_on": None},
    {"id": "RTR-EDGE-2", "type": "router", "name": "Edge Router B1", "site": "SITE_B", "depends_on": "TRANS-CORE-2"},
    {"id": "OLT-B1", "type": "olt", "name": "OLT B1", "site": "SITE_B", "depends_on": "RTR-EDGE-2"},
    {"id": "GNB-B1", "type": "gnodeb", "name": "gNodeB B1", "site": "SITE_B", "depends_on": "RTR-EDGE-2"},
]

# --- Services -------------------------------------------------------------------
SERVICES = [
    {"id": "SVC_MOBILE_DATA", "name": "Mobile Data", "affected_by": ["GNB-A1", "GNB-A2", "GNB-B1"]},
    {"id": "SVC_BROADBAND", "name": "Broadband Internet", "affected_by": ["OLT-A1", "OLT-B1"]},
    {"id": "SVC_VOICE", "name": "Voice", "affected_by": ["GNB-A1", "GNB-A2", "GNB-B1"]},
]

# --- KPI baseline definitions (used to synthesize "healthy" vs "degraded" values) --
KPI_DEFINITIONS = {
    "latency_ms": {"unit": "ms", "healthy_max": 20, "warning_max": 50},
    "packet_loss_pct": {"unit": "%", "healthy_max": 0.5, "warning_max": 3.0},
    "signal_strength_dbm": {"unit": "dBm", "healthy_min": -85, "warning_min": -100},
    "throughput_mbps": {"unit": "Mbps", "healthy_min": 80, "warning_min": 30},
}

# --- Historical incidents (used as GraphRAG retrieval context / few-shot memory) --
HISTORICAL_INCIDENTS = [
    {
        "id": "INC-2025-011",
        "title": "Core transmission outage - fiber cut",
        "root_cause_device": "TRANS-CORE-1",
        "affected_devices": ["TRANS-CORE-1", "RTR-EDGE-1", "OLT-A1", "GNB-A1", "GNB-A2"],
        "summary": (
            "Toan bo cac thiet bi phu thuoc TRANS-CORE-1 (RTR-EDGE-1, OLT-A1, GNB-A1, GNB-A2) "
            "dong loat phat canh bao mat tin hieu trong khi TRANS-CORE-1 bao Link_Down. "
            "Nguyen nhan xac dinh: dut cap quang truc. Xu ly: han noi lai soi quang, "
            "khoi phuc sau 47 phut."
        ),
    },
    {
        "id": "INC-2024-088",
        "title": "Edge router packet loss do lỗi phần cứng",
        "root_cause_device": "RTR-EDGE-2",
        "affected_devices": ["RTR-EDGE-2", "OLT-B1", "GNB-B1"],
        "summary": (
            "RTR-EDGE-2 phat canh bao High_Packet_Loss rieng le, cac thiet bi con (OLT-B1, GNB-B1) "
            "chi suy giam KPI nhe, khong co canh bao mat tin hieu. Nguyen nhan: loi module uplink "
            "cua router. Xu ly: thay module, khong can can thiep len thiet bi con."
        ),
    },
    {
        "id": "INC-2024-052",
        "title": "Su co cell don le",
        "root_cause_device": "GNB-A2",
        "affected_devices": ["GNB-A2"],
        "summary": (
            "GNB-A2 phat Cell_Down trong khi GNB-A1 (cung phu thuoc RTR-EDGE-1) van hoat dong binh "
            "thuong. Nguyen nhan: loi phan cung module vo tuyen tai GNB-A2, khong lien quan router."
        ),
    },
]

# --- Incident scenarios for demo + evaluation --------------------------------
# Each scenario lists the alarms/KPI anomalies observed and the KNOWN ground
# truth root cause, used both to drive the demo and to score rule-only vs
# GraphRAG-only vs combined accuracy in the evaluation module.
SCENARIOS = [
    {
        "id": "SCN-01",
        "name": "Core transmission down - cascading signal loss",
        "description": (
            "TRANS-CORE-1 mat ket noi (Link_Down). Toan bo thiet bi con qua RTR-EDGE-1 "
            "(RTR-EDGE-1, OLT-A1, GNB-A1, GNB-A2) deu phat canh bao mat tin hieu."
        ),
        "alarms": [
            {"device": "TRANS-CORE-1", "type": "LINK_DOWN", "severity": "critical"},
            {"device": "RTR-EDGE-1", "type": "LOSS_OF_SIGNAL", "severity": "critical"},
            {"device": "OLT-A1", "type": "LOSS_OF_SIGNAL", "severity": "major"},
            {"device": "GNB-A1", "type": "CELL_DOWN", "severity": "major"},
            {"device": "GNB-A2", "type": "CELL_DOWN", "severity": "major"},
        ],
        "kpi_anomalies": [],
        "ground_truth_root_cause": "TRANS-CORE-1",
    },
    {
        "id": "SCN-02",
        "name": "Isolated router packet loss",
        "description": (
            "RTR-EDGE-2 co ty le mat goi tin cao (High_Packet_Loss). TRANS-CORE-2 (thiet bi cha) "
            "van hoat dong binh thuong, cac thiet bi con (OLT-B1, GNB-B1) chi suy giam KPI nhe, "
            "khong phat canh bao mat tin hieu."
        ),
        "alarms": [
            {"device": "RTR-EDGE-2", "type": "HIGH_PACKET_LOSS", "severity": "major"},
        ],
        "kpi_anomalies": [
            {"device": "OLT-B1", "kpi": "throughput_mbps", "value": 55, "status": "warning"},
            {"device": "GNB-B1", "kpi": "throughput_mbps", "value": 60, "status": "warning"},
        ],
        "ground_truth_root_cause": "RTR-EDGE-2",
    },
    {
        "id": "SCN-03",
        "name": "Sibling alarms without explicit parent alarm",
        "description": (
            "OLT-A1, GNB-A1 va GNB-A2 (cung phu thuoc RTR-EDGE-1) deu phat canh bao mat tin hieu / "
            "throughput thap, nhung RTR-EDGE-1 khong co canh bao tuong minh (co the do thieu giam sat "
            "hoac canh bao chua kip sinh)."
        ),
        "alarms": [
            {"device": "OLT-A1", "type": "LOSS_OF_SIGNAL", "severity": "major"},
            {"device": "GNB-A1", "type": "LOW_THROUGHPUT", "severity": "major"},
            {"device": "GNB-A2", "type": "LOW_THROUGHPUT", "severity": "major"},
        ],
        "kpi_anomalies": [
            {"device": "RTR-EDGE-1", "kpi": "packet_loss_pct", "value": 4.2, "status": "warning"},
        ],
        "ground_truth_root_cause": "RTR-EDGE-1",
    },
    {
        "id": "SCN-04",
        "name": "Single isolated cell fault",
        "description": (
            "Chi rieng GNB-A2 phat Cell_Down. GNB-A1 (cung phu thuoc RTR-EDGE-1) va cac thiet bi "
            "khac van hoat dong binh thuong."
        ),
        "alarms": [
            {"device": "GNB-A2", "type": "CELL_DOWN", "severity": "major"},
        ],
        "kpi_anomalies": [],
        "ground_truth_root_cause": "GNB-A2",
    },
    {
        "id": "SCN-05",
        "name": "Gradual KPI degradation without hard alarm",
        "description": (
            "OLT-B1 co throughput giam dan xuong duoi nguong canh bao (suy hao soi quang) nhung "
            "chua co canh bao cung (alarm) nao duoc sinh ra."
        ),
        "alarms": [],
        "kpi_anomalies": [
            {"device": "OLT-B1", "kpi": "throughput_mbps", "value": 25, "status": "critical"},
            {"device": "OLT-B1", "kpi": "signal_strength_dbm", "value": -102, "status": "critical"},
        ],
        "ground_truth_root_cause": "OLT-B1",
    },
]
