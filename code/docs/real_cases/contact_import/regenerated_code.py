def deduplicate_contacts(contacts):
    """按 email 去重（忽略首尾空格与大小写），保留首次出现的完整记录。

    不修改输入列表或其中的字典，返回新列表，顺序为首次出现顺序。
    """
    seen = {}
    for contact in contacts:
        email = contact.get("email", "")
        key = email.strip().lower()
        if key not in seen:
            seen[key] = contact
    return list(seen.values())
