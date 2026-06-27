# Payments Webhook Timeout

## Incident History

Webhook timeout incidents happened when retry headers changed and the handler waited on a slow provider acknowledgement.

## Fix Checklist

Run the payments webhook tests, check retry headers, and confirm idempotency keys are preserved.
