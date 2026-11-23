def calculate_payable(items):
    total = sum(float(item['price']) * item['quantity'] for item in items)
    if total >= 100:
        total -= 20
    return f"{total:.2f}"
