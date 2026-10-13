import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.service.qixin_api_service import QixinApiError, QixinApiService


class QixinApiServiceTest(unittest.TestCase):
    def build_config(self):
        return SimpleNamespace(
            qixin_app_key="test-app-key",
            qixin_secret_key="test-secret-key",
            qixin_base_url="https://api.qixin.com/APIService",
            qixin_timeout_seconds=15.0,
        )

    def test_build_auth_headers_uses_official_md5_formula(self):
        service = QixinApiService(config=self.build_config(), transport=lambda *args: {})

        headers = service.build_auth_headers(timestamp=1700000000123)

        expected_sign = hashlib.md5(
            "test-app-key1700000000123test-secret-key".encode("utf-8")
        ).hexdigest()
        self.assertEqual(headers["Auth-Version"], "2.0")
        self.assertEqual(headers["appkey"], "test-app-key")
        self.assertEqual(headers["timestamp"], "1700000000123")
        self.assertEqual(headers["sign"], expected_sign)
        self.assertNotIn("secret_key", headers)

    def test_http_transport_uses_direct_opener_instead_of_environment_proxy(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps({"status": "200", "data": {"name": "测试企业"}}).encode("utf-8")

        direct_opener = Mock()
        direct_opener.open.return_value = FakeResponse()
        with (
            patch("app.service.qixin_api_service.build_opener", create=True, return_value=direct_opener) as build_opener,
            patch(
                "app.service.qixin_api_service.urlopen",
                create=True,
                side_effect=AssertionError("不得使用默认代理链路"),
            ),
        ):
            service = QixinApiService(config=self.build_config())
            payload = service.http_get_json(
                "/enterprise/getBasicInfo",
                {"keyword": "测试企业"},
                {"Accept": "application/json"},
                15.0,
            )

        build_opener.assert_called_once()
        direct_opener.open.assert_called_once()
        self.assertEqual(payload["status"], "200")

    def test_connection_status_reports_direct_egress_ip(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return "当前 IP：14.145.79.63  来自于：中国 广东 广州 电信".encode("utf-8")

        service = QixinApiService(config=self.build_config(), transport=lambda *args: {})
        service.http_opener = Mock()
        service.http_opener.open.return_value = FakeResponse()

        status = service.get_connection_status()

        self.assertTrue(status["configured"])
        self.assertEqual(status["egress_ip"], "14.145.79.63")
        self.assertEqual(status["egress_region"], "中国 广东 广州 电信")

    def test_query_company_merges_basic_contact_and_largest_person_shareholder(self):
        response_map = {
            "/enterprise/getBasicInfo": {
                "status": "200",
                "message": "success",
                "data": {
                    "name": "深圳市测试科技有限公司",
                    "oper_name": "李四",
                    "credit_no": "91440300MA5F12345X",
                    "status": "存续",
                    "scope": "电子产品销售",
                    "address": "广东省深圳市南山区测试路1号",
                },
            },
            "/enterprise/getContactInfo": {
                "status": "200",
                "message": "success",
                "data": {
                    "telephone": "13812349876",
                    "address": "广东省深圳市南山区测试路1号",
                },
            },
            "/enterprise/getPartners": {
                "status": "200",
                "message": "success",
                "data": {
                    "items": [
                        {"name": "王五", "percent": "20%", "type": "自然人股东"},
                        {"name": "张三", "percent": "60%", "type": "自然人股东"},
                        {"name": "某某投资有限公司", "percent": "80%", "type": "企业法人"},
                    ]
                },
            },
        }

        def transport(endpoint, params, headers, timeout):
            self.assertEqual(params["keyword"], "深圳市测试科技有限公司")
            self.assertEqual(headers["Auth-Version"], "2.0")
            self.assertEqual(timeout, 15.0)
            return response_map[endpoint]

        service = QixinApiService(config=self.build_config(), transport=transport)

        result = service.query_company("深圳市测试科技有限公司", "3C数码")

        self.assertEqual(result.lead.suspected_company_name, "深圳市测试科技有限公司")
        self.assertEqual(result.lead.legal_person, "李四")
        self.assertEqual(result.lead.unified_social_credit_code, "91440300MA5F12345X")
        self.assertEqual(result.lead.phone, "13812349876")
        self.assertEqual(result.lead.registered_address, "广东省深圳市南山区测试路1号")
        self.assertEqual(result.lead.contact_name, "法人：李四；最大股东：张三")
        self.assertTrue(result.endpoint_status["basic"]["authorized"])
        self.assertTrue(result.endpoint_status["contact"]["authorized"])
        self.assertTrue(result.endpoint_status["partners"]["authorized"])

    def test_optional_endpoint_denial_keeps_basic_company_result(self):
        def transport(endpoint, params, headers, timeout):
            if endpoint == "/enterprise/getBasicInfo":
                return {
                    "status": "200",
                    "message": "success",
                    "data": {
                        "name": "深圳市测试科技有限公司",
                        "oper_name": "李四",
                        "credit_no": "91440300MA5F12345X",
                    },
                }
            raise QixinApiError("接口未授权", endpoint=endpoint, status="403")

        service = QixinApiService(config=self.build_config(), transport=transport)

        result = service.query_company("深圳市测试科技有限公司", "3C数码")

        self.assertEqual(result.lead.legal_person, "李四")
        self.assertEqual(result.lead.phone, "")
        self.assertFalse(result.endpoint_status["contact"]["authorized"])
        self.assertFalse(result.endpoint_status["partners"]["authorized"])

    def test_query_company_drops_landlines_but_keeps_mobile_and_service_phones(self):
        def transport(endpoint, params, headers, timeout):
            if endpoint == "/enterprise/getBasicInfo":
                return {
                    "status": "200",
                    "message": "操作成功",
                    "data": {"name": "腾讯科技（深圳）有限公司", "oper_name": "马化腾"},
                }
            if endpoint == "/enterprise/getContactInfo":
                return {
                    "status": "200",
                    "message": "操作成功",
                    "data": {
                        "telephone": "86013388，0755-86013388，13812349876，400-123-4567"
                    },
                }
            return {"status": "200", "message": "操作成功", "data": {"items": []}}

        service = QixinApiService(config=self.build_config(), transport=transport)

        result = service.query_company("腾讯科技（深圳）有限公司", "")

        self.assertEqual(result.lead.phone, "13812349876；400-123-4567")
        self.assertEqual(result.lead.phone_source, "启信宝1.51企业联系方式")

    def test_ip_whitelist_error_is_an_authorization_failure(self):
        error = QixinApiError(
            "未添加IP白名单",
            endpoint="/enterprise/getBasicInfo",
            status="104",
        )

        self.assertTrue(error.is_authorization_denied())


if __name__ == "__main__":
    unittest.main()
