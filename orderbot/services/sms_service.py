"""
SMS Service for Orderbot (AWS SNS)
====================================

Sends SMS messages to customers via AWS SNS. When AWS credentials are not
configured (no AWS_ACCESS_KEY_ID), all functions return None for graceful
degradation.

Environment variables:
- AWS_ACCESS_KEY_ID: AWS IAM access key
- AWS_SECRET_ACCESS_KEY: AWS IAM secret key
- AWS_REGION: AWS region (default: us-east-1)
- AWS_SNS_FROM_NUMBER: Origination phone number (e.g., +15551234567)
"""

import logging

from ..config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, AWS_SNS_FROM_NUMBER

logger = logging.getLogger(__name__)

# Lazy-initialize SNS client
_client = None


def _get_client():
    """Lazy-load and configure the AWS SNS client."""
    global _client
    if _client is None:
        try:
            import boto3
            _client = boto3.client(
                "sns",
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_REGION,
            )
        except ImportError:
            logger.warning("boto3 package not installed; SMS features disabled")
            return None
    return _client


def is_sms_configured() -> bool:
    """Check if AWS SNS SMS is properly configured."""
    return bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_SNS_FROM_NUMBER)


def send_sms(to_number: str, body: str) -> str | None:
    """Send an SMS message via AWS SNS.

    Args:
        to_number: Recipient phone number (E.164 format, e.g., +15551234567)
        body: Message text

    Returns:
        SNS MessageId on success, None on failure or if not configured.
    """
    if not is_sms_configured():
        logger.info("SMS not configured; would send to %s: %s", to_number, body[:100])
        return None

    client = _get_client()
    if client is None:
        return None

    try:
        response = client.publish(
            PhoneNumber=to_number,
            Message=body,
            MessageAttributes={
                "AWS.SNS.SMS.OriginationNumber": {
                    "DataType": "String",
                    "StringValue": AWS_SNS_FROM_NUMBER,
                },
                "AWS.SNS.SMS.SMSType": {
                    "DataType": "String",
                    "StringValue": "Transactional",
                },
            },
        )
        message_id = response.get("MessageId")
        logger.info("SMS sent to %s (MessageId: %s)", to_number, message_id)
        return message_id
    except (ConnectionError, TimeoutError, OSError, ValueError) as e:
        logger.error("Failed to send SMS to %s: %s", to_number, e)
        return None
