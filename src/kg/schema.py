"""Knowledge Graph schema for the telecom fault-diagnosis KG.

Mirrors section 5.1 of the đề cương: entities are Device, Alarm, KPI,
Service, Site, Incident; relations capture physical/logical topology,
service dependency and cause-effect links.
"""

# --- Node labels -----------------------------------------------------------
LABEL_DEVICE = "Device"
LABEL_ALARM = "Alarm"
LABEL_KPI = "KPI"
LABEL_SERVICE = "Service"
LABEL_SITE = "Site"
LABEL_INCIDENT = "Incident"

ALL_LABELS = [
    LABEL_DEVICE,
    LABEL_ALARM,
    LABEL_KPI,
    LABEL_SERVICE,
    LABEL_SITE,
    LABEL_INCIDENT,
]

# --- Relationship types ------------------------------------------------------
# Vietnamese term from đề cương given in the comment for traceability.
REL_CONNECTS_TO = "CONNECTS_TO"  # kết_nối_với (Device-Device, physical/logical link)
REL_DEPENDS_ON = "DEPENDS_ON"  # phụ_thuộc_vào (Device-Device, child depends on parent)
REL_BELONGS_TO_SITE = "BELONGS_TO_SITE"  # thuộc_site (Device-Site)
REL_RAISED_ALARM = "RAISED_ALARM"  # gây_ra_cảnh_báo (Device-Alarm)
REL_AFFECTS_SERVICE = "AFFECTS_SERVICE"  # ảnh_hưởng_đến_dịch_vụ (Device-Service)
REL_HAS_KPI = "HAS_KPI"  # (Device-KPI)
REL_PART_OF_INCIDENT = "PART_OF_INCIDENT"  # (Alarm-Incident)
REL_CAUSED_BY = "CAUSED_BY"  # có_nguyên_nhân_từ (Incident-Device, ground-truth root cause)

# Device types observed in the sample topology (BTS/gNodeB, OLT, router, transmission).
DEVICE_TYPES = ["transmission", "router", "olt", "gnodeb"]

# Alarm severities used for simple prioritisation.
ALARM_SEVERITIES = ["critical", "major", "minor", "warning"]
