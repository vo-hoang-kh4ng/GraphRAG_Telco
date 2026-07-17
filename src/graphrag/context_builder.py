"""Converts a retrieved subgraph into structured text context for the LLM
(section 5.2, step 3: "chuyen tieu do thi ... thanh van ban co cau truc").
"""


def build_context_text(subgraph):
    if not subgraph["seed_devices"]:
        return "Khong tim thay thuc the lien quan den su co nay trong Knowledge Graph."

    lines = []

    lines.append("## Thiet bi lien quan (topology, pham vi {} hop quanh thiet bi phat sinh su co)".format(2))
    for d in subgraph["devices"]:
        parents = d.get("parent_ids") or []
        parent_part = f", phu_thuoc_vao={', '.join(parents)}" if parents else " (khong co thiet bi cha - dinh goc)"
        site_part = f", site={d['site_name']}" if d.get("site_name") else ""
        seed_tag = " [DIEM_KHOI_PHAT]" if d["id"] in subgraph["seed_devices"] else ""
        lines.append(f"- {d['id']} (loai={d['type']}, ten={d['name']}{parent_part}{site_part}){seed_tag}")

    lines.append("")
    lines.append("## Canh bao (Alarm) hien tai")
    if subgraph["alarms"]:
        for a in subgraph["alarms"]:
            lines.append(f"- {a['device_id']} phat canh bao {a['type']} (muc do: {a['severity']})")
    else:
        lines.append("- Khong co canh bao nao dang hoat dong trong pham vi tieu do thi nay.")

    lines.append("")
    lines.append("## Chi so KPI bat thuong")
    if subgraph["kpis"]:
        for k in subgraph["kpis"]:
            lines.append(f"- {k['device_id']}: {k['name']} = {k['value']} (trang thai: {k['status']})")
    else:
        lines.append("- Khong co KPI bat thuong nao trong pham vi tieu do thi nay.")

    lines.append("")
    lines.append("## Dich vu bi anh huong")
    if subgraph["services"]:
        for s in subgraph["services"]:
            lines.append(f"- {s['device_id']} anh_huong_den dich vu {s['service_name']}")
    else:
        lines.append("- Khong xac dinh duoc dich vu bi anh huong truc tiep.")

    lines.append("")
    lines.append("## Su co lich su tuong tu (case-based context)")
    if subgraph["historical_incidents"]:
        for h in subgraph["historical_incidents"]:
            lines.append(f"- {h['id']} - {h['title']} (nguyen nhan goc re da xac dinh: {h['root_cause_device']})")
            lines.append(f"  Tom tat: {h['summary']}")
    else:
        lines.append("- Khong tim thay su co lich su nao lien quan truc tiep den cac thiet bi trong pham vi nay.")

    return "\n".join(lines)
