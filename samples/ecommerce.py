"""E-commerce order management with many business rules (expected: HIGH branching)."""

TAX_RATES = {"CA": 0.0725, "NY": 0.08, "TX": 0.0625, "WA": 0.065}


def calculate_discount(subtotal: float, loyalty_years: int, coupon: str) -> float:
    """Return the discount amount for an order."""
    rate = 0.0
    if subtotal >= 500:
        rate = 0.10
    elif subtotal >= 200:
        rate = 0.05
    elif subtotal >= 100:
        rate = 0.02
    if loyalty_years >= 5:
        rate += 0.05
    elif loyalty_years >= 2:
        rate += 0.02
    if coupon == "SAVE10":
        rate += 0.10
    elif coupon == "SAVE20":
        rate += 0.20
    elif coupon == "WELCOME" and loyalty_years == 0:
        rate += 0.15
    return round(subtotal * min(rate, 0.40), 2)


def calculate_shipping(weight: float, country: str, express: bool) -> float:
    """Return the shipping fee."""
    if weight < 0:
        raise ValueError("weight cannot be negative")
    if weight == 0:
        return 0.0
    fee = 5.0 if weight <= 1 else 9.0 if weight <= 5 else 15.0
    if country != "US":
        fee *= 2.5 if country in ("CA", "MX") else 4.0
    if express:
        fee += 12.0
    return round(fee, 2)


def calculate_tax(amount: float, region: str) -> float:
    """Return sales tax for a region (zero for unknown regions)."""
    if amount < 0:
        raise ValueError("amount cannot be negative")
    return round(amount * TAX_RATES.get(region, 0.0), 2)


def classify_order(total: float, items: int, express: bool, country: str) -> str:
    """Return a handling priority label for the warehouse."""
    if total <= 0 or items <= 0:
        return "invalid"
    if express and total > 500:
        return "vip-express"
    if express or (country != "US" and total > 200):
        return "express"
    if total > 1000 and items > 10:
        return "bulk"
    if items > 20 or (total > 300 and country == "US"):
        return "priority"
    return "standard"


class Cart:
    """Shopping cart holding item prices for one customer."""

    def __init__(self, customer: str, loyalty_years: int, prices: list):
        self.customer = customer
        self.loyalty_years = loyalty_years
        self.prices = list(prices)

    def add_price(self, price: float) -> None:
        """Add an item price to the cart."""
        if price <= 0:
            raise ValueError("price must be positive")
        self.prices.append(price)

    def subtotal(self) -> float:
        """Return the sum of all item prices."""
        return round(sum(self.prices), 2)

    def checkout(self, coupon: str, country: str, express: bool) -> dict:
        """Compute discount, shipping, tax and the final total."""
        subtotal = self.subtotal()
        discount = calculate_discount(subtotal, self.loyalty_years, coupon)
        shipping = calculate_shipping(len(self.prices) * 0.8, country, express)
        tax = calculate_tax(subtotal - discount, "CA" if country == "US" else "")
        total = round(subtotal - discount + shipping + tax, 2)
        label = classify_order(total, len(self.prices), express, country)
        return {"subtotal": subtotal, "discount": discount, "shipping": shipping,
                "tax": tax, "total": total, "priority": label}


def main() -> None:
    """Demonstrate an order."""
    cart = Cart("Dana", 3, [120.0, 80.5, 45.25])
    cart.add_price(19.99)
    print(cart.checkout("SAVE10", "US", False))
    print(cart.checkout("", "MX", True))


if __name__ == "__main__":
    main()
