# Reviewed Inbox drafts

Front Desk version 2 adds an Inbox coworker that drafts an administrative reply
from one selected incoming message and its recorded human triage. In Practice
work → Incoming messages, review the patient/thread and matching encounter, record
administrative triage, and choose **Draft a reply**. Review the selected text and
triage, choose an enabled Inbox coworker, and explicitly consent to one AI draft.
The result is private, marked unreviewed, and saved in the encounter conversation.
A person reviews and sends it separately. Clinical/urgent triage stays with a person.

Existing Front Desk version 1 teams remain unchanged. Team settings offers an
explicit Inbox skill upgrade; the draft retains the existing bot identity, name,
preferences, source choices and restrictions. The existing rehearsal/review/save
flow accepts that change. A retired Inbox coworker must be replaced first.

The request includes only the exact incoming text, human administrative triage and
fixed drafting question. It does not include notebook, evidence, conversation
history, working preferences or vendor contact/account identifiers. The current
owner, Box, patient, grant, source, review, triage, encounter and team are checked
at admission, before dispatch and before result disclosure. Existing model attempt
limits and exact-request recovery apply. A changed source or revoked read grant
withholds a new result while retaining the attempt. An unresolved request is
checked using its original key and selection; a new request requires source review
and fresh consent. No automatic reply, notification, clinical action or appointment
change is performed by this capability.

The compiled team contract is 3. Normal identity and activity reads retain their
existing contract 2. API, web and both native packages must be updated together;
the compatibility gate withholds mismatched clients. The database schema is unchanged.
Athena remains read-only. Real Inbox/provider activation and physical-device
acceptance remain separate requirements.
