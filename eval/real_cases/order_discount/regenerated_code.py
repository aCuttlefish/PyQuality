from decimal import Decimal, ROUND_HALF_UP


def calculate_payable(items):
    total = Decimal('0.00')
    for item in items:
        price = Decimal(str(item['price']))
        quantity = int(item['quantity'])
        total += price * quantity
    if total >= Decimal('100.00'):
        total -= Decimal('20.00')
    return str(total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
