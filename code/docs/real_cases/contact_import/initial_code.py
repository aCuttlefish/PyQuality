def deduplicate_contacts(contacts):
    """按 email 去重联系人，保留每个邮箱首次出现的联系人。

    :param contacts: 联系人字典列表，每条包含 'name' 和 'email'
    :return: 去重后的联系人列表
    """
    seen = {}
    for contact in contacts:
        email = contact.get('email')
        if email not in seen:
            seen[email] = contact
    return list(seen.values())
