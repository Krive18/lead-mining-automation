import unittest

from app.service.collector_service import EnterprisePublicWebCollector


class EnterprisePublicWebAddressTest(unittest.TestCase):
    def setUp(self):
        self.collector = EnterprisePublicWebCollector.create_qixin_collector()

    def test_extracts_enterprise_address_without_phone_noise(self):
        text = (
            "\u4f01\u4e1a\u5730\u5740\uff1a"
            "\u5e7f\u4e1c\u7701\u6df1\u5733\u5e02\u5b9d\u5b89\u533a"
            "\u822a\u57ce\u8857\u905388\u53f7 "
            "\u7535\u8bdd\uff1a13800138000"
        )

        address = self.collector.extract_registered_address(text)

        self.assertEqual(
            address,
            "\u5e7f\u4e1c\u7701\u6df1\u5733\u5e02\u5b9d\u5b89\u533a"
            "\u822a\u57ce\u8857\u905388\u53f7",
        )

    def test_extracts_contact_address_without_map_noise(self):
        text = (
            "\u8054\u7cfb\u5730\u5740\uff1a"
            "\u5e7f\u4e1c\u7701\u4e1c\u839e\u5e02\u957f\u5b89\u9547"
            "\u632f\u5b89\u8def6\u53f7 "
            "\u9644\u8fd1\u4f01\u4e1a \u5730\u56fe\u5bfc\u822a"
        )

        address = self.collector.extract_registered_address(text)

        self.assertEqual(
            address,
            "\u5e7f\u4e1c\u7701\u4e1c\u839e\u5e02\u957f\u5b89\u9547"
            "\u632f\u5b89\u8def6\u53f7",
        )

    def test_extracts_mailing_address_without_website_noise(self):
        text = (
            "\u901a\u8baf\u5730\u5740 "
            "\u5e7f\u4e1c\u7701\u5e7f\u5dde\u5e02\u767d\u4e91\u533a"
            "\u5609\u79be\u8857\u9053\u671b\u5c97\u5de5\u4e1a\u533a "
            "\u5b98\u7f51\uff1awww.example.com"
        )

        address = self.collector.extract_registered_address(text)

        self.assertEqual(
            address,
            "\u5e7f\u4e1c\u7701\u5e7f\u5dde\u5e02\u767d\u4e91\u533a"
            "\u5609\u79be\u8857\u9053\u671b\u5c97\u5de5\u4e1a\u533a",
        )

    def test_extracts_embedded_address_without_map_json_code(self):
        text = (
            "\u4f01\u4e1a\u5730\u5740 "
            '","sourceDisplayWeight":1,"reportYear":null,'
            '"longitude":"113.79763796117372","latitude":"23.064117281926208"}],'
            '"address":"\u5e7f\u4e1c\u7701\u4e1c\u839e\u5e02\u864e\u95e8\u9547'
            '\u592a\u6c99\u8def285\u53f71006\u623f","showSource":1'
        )

        address = self.collector.extract_registered_address(text)

        self.assertEqual(
            address,
            "\u5e7f\u4e1c\u7701\u4e1c\u839e\u5e02\u864e\u95e8\u9547"
            "\u592a\u6c99\u8def285\u53f71006\u623f",
        )

    def test_drops_map_json_when_no_address_is_embedded(self):
        text = (
            "\u4f01\u4e1a\u5730\u5740 "
            '","sourceDisplayWeight":1,"reportYear":null,'
            '"longitude":"113.79763796117372","latitude":"23.064117281926208"}],'
            '"fromTime":1686585600000,"socialStaffNum":"-"'
        )

        address = self.collector.extract_registered_address(text)

        self.assertEqual(address, "")

    def test_removes_business_scope_after_nearby_company_suffix(self):
        text = (
            "\u4f01\u4e1a\u5730\u5740\uff1a"
            "\u5e7f\u5dde\u5e02\u767d\u4e91\u533a\u9e64\u9f99\u8857"
            "\u9e64\u8fb9\u901a\u8fbe\u521b\u610f\u56ed\u897f\u533a\u4e8c\u6a2a\u8def1\u53f7"
            "\u7b2c10\u680b228\u5ba4\u9644\u8fd1\u516c\u53f8 \u7ecf\u8425\u8303\u56f4 "
            "\u670d\u88c5\u5236\u9020;\u5316\u5986\u54c1\u6279\u53d1;\u6280\u672f\u670d\u52a1"
        )

        address = self.collector.extract_registered_address(text)

        self.assertEqual(
            address,
            "\u5e7f\u5dde\u5e02\u767d\u4e91\u533a\u9e64\u9f99\u8857"
            "\u9e64\u8fb9\u901a\u8fbe\u521b\u610f\u56ed\u897f\u533a\u4e8c\u6a2a\u8def1\u53f7"
            "\u7b2c10\u680b228\u5ba4",
        )

    def test_cleans_change_log_to_latest_address_only(self):
        text = (
            "\u4f01\u4e1a\u5730\u5740\uff1a\u53d8\u66f4\uff1a\u4ece\u201c"
            "\u5e7f\u5dde\u5e02\u82b1\u90fd\u533a\u65b0\u534e\u8857\u56e2\u7ed3\u6751\u673a\u573a\u5b89\u7f6e\u5317\u533a"
            "\u201d\u53d8\u66f4\u4e3a\u201c"
            "\u5e7f\u5dde\u5e02\u82b1\u90fd\u533a\u51e4\u51f0\u6751\u666f\u5929\u5927\u9053\u53171\u53f7302"
            "\u201d\u67e5\u770b\u52a8\u6001"
        )

        address = self.collector.extract_registered_address(text)

        self.assertEqual(
            address,
            "\u5e7f\u5dde\u5e02\u82b1\u90fd\u533a\u51e4\u51f0\u6751\u666f\u5929\u5927\u9053\u53171\u53f7302",
        )

    def test_extracts_unified_social_credit_code_from_labeled_field(self):
        code = self.collector.extract_unified_social_credit_code(
            "统一社会信用代码：91440101MA5CKX7R2L 法定代表人：张三"
        )

        self.assertEqual(code, "91440101MA5CKX7R2L")

    def test_does_not_treat_registration_capital_as_credit_code(self):
        code = self.collector.extract_unified_social_credit_code(
            "注册资本：100万元 成立日期：2020-01-01"
        )

        self.assertEqual(code, "")


if __name__ == "__main__":
    unittest.main()
