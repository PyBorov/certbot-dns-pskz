"""Unit tests for the ps.kz Certbot DNS plugin.

All HTTP calls are mocked — these tests never hit the real ps.kz API.
"""
from unittest import mock

import pytest
from certbot import errors

from certbot_dns_pskz import _PSKZClient


def _resp(json_data):
    resp = mock.Mock()
    resp.json.return_value = json_data
    resp.raise_for_status = mock.Mock()
    return resp


class TestFindZone:
    def test_exact_domain_match(self, mocker):
        client = _PSKZClient("token")
        mock_post = mocker.patch.object(client.session, "post")
        mock_post.return_value = _resp(
            {"data": {"dns": {"zones": {"items": [{"name": "example.kz."}]}}}}
        )

        zone = client._find_zone("example.kz")

        assert zone == "example.kz."
        mock_post.assert_called_once()

    def test_walks_up_labels_until_match(self, mocker):
        client = _PSKZClient("token")
        mock_post = mocker.patch.object(client.session, "post")
        # First lookup (wiki.example.kz) finds nothing, second (example.kz) matches
        mock_post.side_effect = [
            _resp({"data": {"dns": {"zones": {"items": []}}}}),
            _resp(
                {"data": {"dns": {"zones": {"items": [{"name": "example.kz."}]}}}}
            ),
        ]

        zone = client._find_zone("wiki.example.kz")

        assert zone == "example.kz."
        assert mock_post.call_count == 2
        second_call_vars = mock_post.call_args_list[1].kwargs["json"]["variables"]
        assert second_call_vars["s"] == "example.kz"

    def test_raises_when_no_zone_accessible(self, mocker):
        client = _PSKZClient("token")
        mock_post = mocker.patch.object(client.session, "post")
        mock_post.return_value = _resp(
            {"data": {"dns": {"zones": {"items": []}}}}
        )

        with pytest.raises(errors.PluginError):
            client._find_zone("nonexistent.example")

    def test_ignores_non_matching_zones_in_response(self, mocker):
        # Regression test: the API previously returned an unrelated zone
        # first (e.g. valis.kz for a wiki.example.kz lookup); make sure we
        # only accept an exact (dot-stripped) name match, not "any item".
        client = _PSKZClient("token")
        mock_post = mocker.patch.object(client.session, "post")
        mock_post.return_value = _resp(
            {
                "data": {
                    "dns": {
                        "zones": {
                            "items": [
                                {"name": "unrelated-zone.kz."},
                            ]
                        }
                    }
                }
            }
        )

        with pytest.raises(errors.PluginError):
            client._find_zone("example.kz")


class TestAddTxtRecord:
    def test_creates_record_in_resolved_zone(self, mocker):
        client = _PSKZClient("token")
        mock_post = mocker.patch.object(client.session, "post")
        mock_post.side_effect = [
            _resp(
                {"data": {"dns": {"zones": {"items": [{"name": "example.kz."}]}}}}
            ),
            _resp({"data": {"dns": {"record": {"create": {"name": "example.kz."}}}}}),
        ]

        client.add_txt_record(
            "example.kz", "_acme-challenge.example.kz", "validation-token"
        )

        assert mock_post.call_count == 2
        create_payload = mock_post.call_args_list[1].kwargs["json"]
        record_data = create_payload["variables"]["recordData"]
        assert record_data["type"] == "TXT"
        assert record_data["value"] == "validation-token"
        assert record_data["name"] == "_acme-challenge.example.kz."
        assert create_payload["variables"]["zoneName"] == "example.kz."

    def test_raises_on_api_error(self, mocker):
        client = _PSKZClient("token")
        mock_post = mocker.patch.object(client.session, "post")
        mock_post.side_effect = [
            _resp(
                {"data": {"dns": {"zones": {"items": [{"name": "example.kz."}]}}}}
            ),
            _resp({"errors": [{"message": "insufficient permissions"}]}),
        ]

        with pytest.raises(errors.PluginError):
            client.add_txt_record(
                "example.kz", "_acme-challenge.example.kz", "validation-token"
            )


class TestDelTxtRecord:
    def test_deletes_matching_record(self, mocker):
        client = _PSKZClient("token")
        mock_post = mocker.patch.object(client.session, "post")
        mock_post.side_effect = [
            _resp(
                {"data": {"dns": {"zones": {"items": [{"name": "example.kz."}]}}}}
            ),
            _resp(
                {
                    "data": {
                        "dns": {
                            "zone": {
                                "records": [
                                    {
                                        "id": "rec-1",
                                        "name": "_acme-challenge.example.kz.",
                                        "type": "TXT",
                                        "value": "validation-token",
                                    },
                                    {
                                        "id": "rec-2",
                                        "name": "www.example.kz.",
                                        "type": "A",
                                        "value": "1.2.3.4",
                                    },
                                ]
                            }
                        }
                    }
                }
            ),
            _resp({"data": {"dns": {"record": {"delete": {"id": "rec-1"}}}}}),
        ]

        client.del_txt_record(
            "example.kz", "_acme-challenge.example.kz", "validation-token"
        )

        assert mock_post.call_count == 3
        delete_payload = mock_post.call_args_list[2].kwargs["json"]
        assert delete_payload["variables"]["recordId"] == "rec-1"
        assert delete_payload["variables"]["zoneName"] == "example.kz."

    def test_noop_when_record_not_found(self, mocker):
        client = _PSKZClient("token")
        mock_post = mocker.patch.object(client.session, "post")
        mock_post.side_effect = [
            _resp(
                {"data": {"dns": {"zones": {"items": [{"name": "example.kz."}]}}}}
            ),
            _resp({"data": {"dns": {"zone": {"records": []}}}}),
        ]

        # Should not raise, and should not attempt a delete mutation.
        client.del_txt_record(
            "example.kz", "_acme-challenge.example.kz", "validation-token"
        )

        assert mock_post.call_count == 2

    def test_noop_when_zone_cannot_be_resolved(self, mocker):
        client = _PSKZClient("token")
        mock_post = mocker.patch.object(client.session, "post")
        mock_post.return_value = _resp(
            {"data": {"dns": {"zones": {"items": []}}}}
        )

        # Cleanup must never raise, even if the zone lookup fails —
        # certbot cleanup hooks are best-effort by convention.
        client.del_txt_record(
            "nonexistent.example",
            "_acme-challenge.nonexistent.example",
            "validation-token",
        )
