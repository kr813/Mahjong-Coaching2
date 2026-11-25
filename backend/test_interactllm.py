import json
import os
from urllib.parse import urlsplit
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import interactllm


def chat_response(text):
    return SimpleNamespace(
        data=SimpleNamespace(message=SimpleNamespace(content=SimpleNamespace(text=text))),
        headers={"opc-request-id": "test-request"},
    )


class OciClientEndpointTest(unittest.TestCase):
    def test_instance_principals_uses_sdk_regional_endpoint(self):
        interactllm._get_client_and_signer.cache_clear()
        self.addCleanup(interactllm._get_client_and_signer.cache_clear)
        with patch("oci.auth.signers.InstancePrincipalsSecurityTokenSigner.__init__", return_value=None):
            client = interactllm._get_client_and_signer("ap-tokyo-1")
        self.assertEqual(
            urlsplit(client.base_client.endpoint).hostname,
            "agent-runtime.generativeai.ap-tokyo-1.oci.oraclecloud.com",
        )


class AdviceGenerationTest(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.create_session.side_effect = [
            SimpleNamespace(data=SimpleNamespace(id=session_id))
            for session_id in ("first", "second")
        ]
        client_patch = patch("interactllm._get_client_and_signer", return_value=self.client)
        self.get_client = client_patch.start()
        self.addCleanup(client_patch.stop)

    def test_complete_advice_sends_only_situation_and_profile(self):
        self.client.chat.return_value = chat_response("安全牌を残しましょう。\n[[ADVICE_COMPLETE]]\n")
        record = {"meta": {"kyoku": "東1局"}, "decision": {}}

        self.assertEqual(interactllm._generate_advice(record), "安全牌を残しましょう。")

        self.client.chat.assert_called_once()
        details = self.client.chat.call_args.kwargs["chat_details"]
        self.assertEqual(json.loads(details.user_message), {
            "situation": interactllm._format_record(record),
            "response_profile": "standard",
        })
        self.assertFalse(details.should_stream)

    def test_missing_marker_retries_once_in_new_session_with_same_situation(self):
        self.client.chat.side_effect = [
            chat_response("ここでは安全牌を"),
            chat_response("安全牌を残しましょう。\n[[ADVICE_COMPLETE]]"),
        ]
        self.assertEqual(interactllm._generate_advice({}), "安全牌を残しましょう。")

        first, second = [call.kwargs["chat_details"] for call in self.client.chat.call_args_list]
        first_payload, second_payload = [json.loads(details.user_message) for details in (first, second)]
        self.assertEqual(first_payload["response_profile"], "standard")
        self.assertEqual(second_payload["response_profile"], "compact")
        self.assertEqual(first_payload["situation"], second_payload["situation"])
        self.assertEqual((first.session_id, second.session_id), ("first", "second"))

    def test_empty_and_marker_only_responses_return_no_advice(self):
        self.client.chat.side_effect = [chat_response(None), chat_response("[[ADVICE_COMPLETE]]")]
        self.assertIsNone(interactllm._generate_advice({}))
        self.assertEqual(self.client.chat.call_count, 2)

    def test_session_creation_failure_still_allows_chat(self):
        self.client.create_session.side_effect = RuntimeError("sessions disabled")
        self.client.chat.return_value = chat_response("助言です。\n[[ADVICE_COMPLETE]]")
        self.assertEqual(interactllm._generate_advice({}), "助言です。")
        self.assertIsNone(self.client.chat.call_args.kwargs["chat_details"].session_id)

    def test_endpoint_override_uses_its_region_and_id_for_both_attempts(self):
        endpoint_id = "ocid1.genaiagentendpoint.oc1.ap-tokyo-1.testendpoint"
        self.client.chat.side_effect = [
            chat_response("途中で"),
            chat_response("最後まで書いた助言です。\n[[ADVICE_COMPLETE]]"),
        ]
        with patch.dict(os.environ, {"OCI_AGENT_ENDPOINT_OCID": f" {endpoint_id} "}):
            self.assertEqual(interactllm._generate_advice({}), "最後まで書いた助言です。")
        self.get_client.assert_called_once_with("ap-tokyo-1")
        for method in (self.client.create_session, self.client.chat):
            self.assertEqual(
                [call.kwargs["agent_endpoint_id"] for call in method.call_args_list],
                [endpoint_id, endpoint_id],
            )

    def test_blank_endpoint_override_uses_default(self):
        self.client.chat.return_value = chat_response("助言です。\n[[ADVICE_COMPLETE]]")
        with patch.dict(os.environ, {"OCI_AGENT_ENDPOINT_OCID": " "}):
            self.assertEqual(interactllm._generate_advice({}), "助言です。")
        self.get_client.assert_called_once_with("ap-osaka-1")
        self.assertEqual(
            self.client.chat.call_args.kwargs["agent_endpoint_id"],
            interactllm.DEFAULT_AGENT_ENDPOINT_OCID,
        )

    def test_chat_error_returns_no_advice(self):
        self.client.chat.side_effect = RuntimeError("service unavailable")
        self.assertIsNone(interactllm._generate_advice({}))
        self.client.chat.assert_called_once()
