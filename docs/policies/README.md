# Synthetic policy documents

**Everything in this folder is fictional.** These documents were written for the CampusGPT
project to give the chatbot something to retrieve and cite. They do not describe the rules
of any real university, and none of the figures should be relied on.

They are loaded into the database by `make seed` (or `make policies`), through the same
extract → chunk → embed pipeline that the admin upload uses. Each file is one document:
the first `#` heading is its title and `##`/`###` headings become citable sections.

| File | Category |
|---|---|
| attendance-policy.md | academic |
| examination-regulations.md | examinations |
| fee-policy.md | fees |
| hostel-rules.md | hostel |
| scholarship-scheme.md | scholarships |
| academic-integrity.md | academic |
