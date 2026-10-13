import unittest

from app.util.product_name_util import (
    is_non_product_label,
    repair_product_name_for_source,
    repair_product_name_from_public_fields,
)


class ProductNameUtilTest(unittest.TestCase):
    def test_treats_city_and_year_as_non_product_label(self):
        self.assertTrue(is_non_product_label("9年"))
        self.assertTrue(is_non_product_label("西安"))
        self.assertTrue(is_non_product_label("北京"))
        self.assertTrue(is_non_product_label("衡阳"))
        self.assertTrue(is_non_product_label("韶关 7年"))
        self.assertTrue(is_non_product_label("上海 9年"))
        self.assertTrue(is_non_product_label("青岛 17年"))

    def test_repairs_bad_clothing_product_from_business_scope(self):
        repaired = repair_product_name_from_public_fields(
            product_name="9年",
            industry="服装",
            source_keyword="东莞服装工厂",
            business_scope=(
                "一般项目：服装服饰零售；服装服饰批发；服饰制造；"
                "针纺织品销售；服装辅料销售；鞋帽零售；箱包销售。"
            ),
            registered_address="广东省东莞市虎门镇附近公司经营范围一般项目：服装服饰零售",
        )

        self.assertEqual(repaired, "服装服饰、服饰制造、针纺织品")

    def test_keeps_existing_precise_category(self):
        repaired = repair_product_name_from_public_fields(
            product_name="女士家居服 睡裙 情侣家居服",
            industry="服装",
            source_keyword="广州服装工厂",
            business_scope="服装服饰批发；服装制造",
            registered_address="",
        )

        self.assertEqual(repaired, "女士家居服 睡裙 情侣家居服")

    def test_alibaba_1688_does_not_repair_empty_product_from_keyword(self):
        repaired = repair_product_name_for_source(
            product_name="",
            industry="美妆个护",
            source_keyword="清远美妆蛋工厂",
            business_scope="化妆品生产；日用化学产品制造；化妆品批发；互联网销售。",
            registered_address="清远市清城区石角镇广州（清远）产业转移工业园附近公司",
            source_type="alibaba_1688",
        )

        self.assertEqual(repaired, "")

    def test_alibaba_1688_keeps_existing_list_card_product(self):
        repaired = repair_product_name_for_source(
            product_name="粉扑、美妆蛋、洗脸扑",
            industry="美妆个护",
            source_keyword="清远美妆蛋工厂",
            business_scope="化妆品生产；日用化学产品制造；化妆品批发；互联网销售。",
            registered_address="清远市清城区石角镇广州（清远）产业转移工业园附近公司",
            source_type="alibaba_1688",
        )

        self.assertEqual(repaired, "粉扑、美妆蛋、洗脸扑")

    def test_alibaba_1688_keeps_visible_single_card_product_even_when_it_matches_keyword(self):
        repaired = repair_product_name_for_source(
            product_name="\u624b\u673a\u6570\u636e\u7ebf",
            industry="3C\u6570\u7801",
            source_keyword="\u6df1\u5733\u624b\u673a\u6570\u636e\u7ebf\u5de5\u5382",
            business_scope="",
            registered_address="",
            source_type="alibaba_1688",
        )

        self.assertEqual(repaired, "\u624b\u673a\u6570\u636e\u7ebf")

    def test_repairs_bad_3c_product_from_business_scope(self):
        repaired = repair_product_name_from_public_fields(
            product_name="13年",
            industry="3C数码",
            source_keyword="东莞3C批发",
            business_scope="一般项目：电线、电缆经营；通讯设备销售；电子产品销售；移动终端设备销售。",
            registered_address="",
        )

        self.assertEqual(repaired, "电线电缆、通讯设备、电子产品")

    def test_repairs_generic_clothing_product_from_business_scope(self):
        repaired = repair_product_name_from_public_fields(
            product_name="服装产品",
            industry="服装",
            source_keyword="东莞服装工厂",
            business_scope="一般项目：服装制造；服装服饰批发；服装辅料销售；鞋帽零售；箱包销售。",
            registered_address="",
        )

        self.assertEqual(repaired, "服装制造、服装服饰、服装辅料")

    def test_repairs_generic_clothing_product_from_short_business_scope(self):
        repaired = repair_product_name_from_public_fields(
            product_name="服装产品",
            industry="服装",
            source_keyword="东莞服装工厂",
            business_scope="产销：服饰、服装、手袋、帽、皮具。",
            registered_address="",
        )

        self.assertEqual(repaired, "服饰、服装、手袋箱包")


if __name__ == "__main__":
    unittest.main()
