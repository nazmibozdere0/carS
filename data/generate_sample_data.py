"""
Generates placeholder car listing data for local development.

Run with: python3 data/generate_sample_data.py
Writes: data/car_listings.json
"""
import json
import random

random.seed(42)

MAKES_MODELS = [
    ("Toyota", "Camry"), ("Toyota", "Corolla"), ("Toyota", "RAV4"), ("Toyota", "Highlander"),
    ("Honda", "Civic"), ("Honda", "Accord"), ("Honda", "CR-V"), ("Honda", "Pilot"),
    ("Ford", "F-150"), ("Ford", "Mustang"), ("Ford", "Escape"), ("Ford", "Explorer"),
    ("Chevrolet", "Silverado"), ("Chevrolet", "Malibu"), ("Chevrolet", "Equinox"),
    ("BMW", "3 Series"), ("BMW", "5 Series"), ("BMW", "X3"),
    ("Mercedes-Benz", "C-Class"), ("Mercedes-Benz", "E-Class"), ("Mercedes-Benz", "GLC"),
    ("Volkswagen", "Jetta"), ("Volkswagen", "Golf"), ("Volkswagen", "Tiguan"),
    ("Hyundai", "Elantra"), ("Hyundai", "Tucson"), ("Hyundai", "Sonata"),
    ("Kia", "Optima"), ("Kia", "Sportage"), ("Kia", "Soul"),
    ("Subaru", "Outback"), ("Subaru", "Forester"), ("Subaru", "Impreza"),
    ("Nissan", "Altima"), ("Nissan", "Rogue"), ("Nissan", "Sentra"),
    ("Mazda", "Mazda3"), ("Mazda", "CX-5"),
    ("Tesla", "Model 3"), ("Tesla", "Model Y"),
    ("Audi", "A4"), ("Audi", "Q5"),
    ("Jeep", "Grand Cherokee"), ("Jeep", "Wrangler"),
    ("Lexus", "RX 350"), ("Lexus", "ES 350"),
]

FUEL_TYPES_BY_MODEL = {
    "Model 3": "Electric",
    "Model Y": "Electric",
}
DEFAULT_FUEL_WEIGHTS = ["Gasoline"] * 6 + ["Hybrid"] * 2 + ["Diesel"] * 1 + ["Electric"] * 1

COLORS = ["black", "white", "silver", "gray", "blue", "red", "dark green", "beige"]
CONDITIONS = ["excellent", "very good", "good", "well-maintained", "like new"]
FEATURES = [
    "backup camera", "heated seats", "Apple CarPlay", "Android Auto", "sunroof",
    "leather seats", "adaptive cruise control", "blind spot monitoring",
    "third-row seating", "navigation system", "keyless entry", "all-wheel drive",
    "lane departure warning", "premium sound system", "remote start",
]
SELLER_NOTES = [
    "Single owner, garage kept.",
    "Clean title, no accidents reported.",
    "Recently serviced with new brakes and tires.",
    "Non-smoker vehicle, no pet odors.",
    "Regularly maintained with full service records.",
    "Priced to sell quickly, motivated seller.",
    "Great commuter car with excellent fuel economy.",
    "Perfect for families needing extra space.",
]


def make_description(year, make, model, mileage, fuel, color, condition, features, note):
    feature_text = ", ".join(features)
    return (
        f"{year} {make} {model} in {color} with {mileage:,} miles. "
        f"Runs in {condition} condition. Fuel type: {fuel}. "
        f"Equipped with {feature_text}. {note}"
    )


def generate_listing(listing_id):
    make, model = random.choice(MAKES_MODELS)
    year = random.randint(2014, 2024)
    age = 2026 - year
    mileage = max(1000, int(random.gauss(age * 11000, 4000)))

    fuel = FUEL_TYPES_BY_MODEL.get(model, random.choice(DEFAULT_FUEL_WEIGHTS))

    base_price_by_make = {
        "Toyota": 24000, "Honda": 24000, "Ford": 26000, "Chevrolet": 25000,
        "BMW": 38000, "Mercedes-Benz": 42000, "Volkswagen": 24000, "Hyundai": 22000,
        "Kia": 22000, "Subaru": 26000, "Nissan": 23000, "Mazda": 24000,
        "Tesla": 40000, "Audi": 40000, "Jeep": 30000, "Lexus": 42000,
    }
    base = base_price_by_make.get(make, 25000)
    depreciation = age * random.uniform(1200, 2200)
    price = max(4000, round(base - depreciation + random.uniform(-1500, 1500), -2))

    color = random.choice(COLORS)
    condition = random.choice(CONDITIONS)
    features = random.sample(FEATURES, k=random.randint(3, 6))
    note = random.choice(SELLER_NOTES)

    return {
        "id": listing_id,
        "make": make,
        "model": model,
        "year": year,
        "mileage": mileage,
        "price": int(price),
        "fuel_type": fuel,
        "description": make_description(year, make, model, mileage, fuel, color, condition, features, note),
    }


def main():
    listings = [generate_listing(i) for i in range(1, 61)]
    with open("data/car_listings.json", "w") as f:
        json.dump(listings, f, indent=2)
    print(f"Wrote {len(listings)} listings to data/car_listings.json")


if __name__ == "__main__":
    main()
