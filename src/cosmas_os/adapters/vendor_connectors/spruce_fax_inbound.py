"""Spruce fax document discovery. Signed-URL fetching explicitly remains closed."""

from urllib.parse import quote, urlencode, urlsplit

from cosmas_os.ports.fax_inbound import (
    InboundFailure,
    ReceivedFax,
    WirePlan,
    bounded_json,
    checked_page,
    timestamp,
)


class SpruceFaxInbound:
    @staticmethod
    def list_plan(scope):
        if (
            scope.selection.vendor != "spruce"
            or scope.selection.environment != "production"
            or not scope.conversation_id
            or not scope.internal_endpoint_id
            or any(
                not value.replace("_", "").isalnum() or len(value) > 128
                for value in (scope.conversation_id, scope.internal_endpoint_id)
            )
        ):
            raise InboundFailure("reviewed_fax_conversation_required")
        return WirePlan(
            "GET",
            "/v1/conversations/"
            + quote(scope.conversation_id, safe="")
            + "/items?"
            + urlencode({"pageSize": scope.limit, "startFrom": scope.starts_at.isoformat()}),
        )

    @staticmethod
    def parse(scope, raw, parent_raw, now):
        SpruceFaxInbound.list_plan(scope)
        parent = bounded_json(parent_raw).get("conversation")
        if (
            type(parent) is not dict
            or parent.get("id") != scope.conversation_id
            or parent.get("type") != "fax"
            or type(parent.get("internalEndpoint")) is not dict
            or parent["internalEndpoint"].get("id") != scope.internal_endpoint_id
            or parent["internalEndpoint"].get("channel") != "fax"
            or parent["internalEndpoint"].get("isInternal") is not True
        ):
            raise InboundFailure("source_changed")
        data = bounded_json(raw)
        if type(data.get("conversationItems")) is not list:
            raise InboundFailure("metadata_invalid")
        items = []
        for row in data["conversationItems"]:
            if (
                type(row) is not dict
                or row.get("conversationId") != scope.conversation_id
                or row.get("direction") != "inbound"
                or row.get("isInternalNote") is not False
                or type(row.get("id")) is not str
                or not row["id"].replace("_", "").isalnum()
                or len(row["id"]) > 128
                or type(row.get("attachments")) is not list
            ):
                raise InboundFailure("source_changed")
            attachments = row["attachments"]
            if (
                len(attachments) != 1
                or type(attachments[0]) is not dict
                or attachments[0].get("type") != "document"
            ):
                raise InboundFailure("attachment_ambiguous")
            doc = attachments[0].get("data")
            if type(doc) is not dict or doc.get("mimetype") != "application/pdf":
                raise InboundFailure("attachment_unsupported")
            signed = doc.get("signedUrl")
            if (
                type(signed) is not dict
                or type(signed.get("url")) is not str
                or len(signed["url"]) > 4096
            ):
                raise InboundFailure("attachment_unsupported")
            url = urlsplit(signed["url"])
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.fragment
            ):
                raise InboundFailure("attachment_unsupported")
            if timestamp(signed.get("expiresAt")) <= now:
                raise InboundFailure("attachment_expired")
            # Host policy is not documented/installed. A URL alone grants no fetch authority.
            items.append(
                ReceivedFax(
                    scope.key(),
                    (scope.conversation_id, row["id"], "0"),
                    timestamp(row.get("createdAt")),
                    0,
                    None,
                    None,
                    False,
                    "download_host_unverified",
                    signed["url"],
                )
            )
        return checked_page(scope, raw, items)

    @staticmethod
    def image_plan(scope, source, approval, now):
        approval.check(scope, source, now)
        raise InboundFailure("download_host_unverified")
