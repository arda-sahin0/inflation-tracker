import pytest

from tracker.naming import parse_size, suggest_id


@pytest.mark.parametrize("name, unit, amount", [
    ("Sek Yeni Nesil Pastörize Günlük Süt 1 L", "PIECE", 1000),
    ("Migros Ayçiçek Yağı 5 L", "PIECE", 5000),
    ("Master Farm Yerli Ceviz İçi 150 G", "PIECE", 150),
    ("Reis Pilavlık Bulgur 1 Kg", "PIECE", 1000),          # a stated size means a package
    ("Muz Yerli Kg", "GRAM", None),                        # "kg" with no number: sold by weight
    ("Domates Kg", "GRAM", None),
    ("Kızılay Erzincan Doğal Maden Suyu 6 x 200 ml", "PIECE", 1200),
    ("Coca-Cola Zero Sugar Kutu 6x250 ml", "PIECE", 1500),
    ("Mr.Oxy Çamaşır Deterjanı 1.480 ml", "PIECE", 1480),  # Turkish thousands separator
    ("Sütaş Yarım Yağlı Süt 1,5 L", "PIECE", 1500),        # Turkish decimal comma
    ("Yumurta L Boy 15'li", "PIECE", None),                # counted, no egg weight given
    ("Yumurta 20'li XL 73 G", "PIECE", 1460),               # 73 g is ONE egg: 20 x 73
    ("Abalı Çiftliği Yumurta M Boy 30'lu 53-62 G", "PIECE", 1725),   # middle of the range, as A101 does
    ("Keskinoglu 15'li L Büyük Boy  Yumurta (63-72 G)", "PIECE", 1012.5),
    ("Sofra Ekmek Adet", "PIECE", None),
])
def test_parse_size(name, unit, amount):
    assert parse_size(name) == (unit, amount if amount is None else pytest.approx(amount))


def test_suggest_id_is_slugged_sized_and_store_tagged():
    assert suggest_id("Çaykur Tiryaki Çayı 1 Kg", "migros") == "caykur-tiryaki-cayi-1kg-migros"
    assert suggest_id("Muz Yerli Kg", "a101") == "muz-yerli-kg-a101"
