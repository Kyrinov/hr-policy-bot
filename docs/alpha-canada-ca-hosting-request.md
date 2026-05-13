# alpha.canada.ca Hosting Request — DND HR Policy Bot

## Overview

alpha.canada.ca is a Government of Canada domain for digital prototypes, managed by CDS via Terraform PRs to the [cds-snc/dns](https://github.com/cds-snc/dns) GitHub repository. This document captures everything needed to submit a subdomain request for this prototype.

---

## Pre-Requisite: Confirm the Render Hostname

Before submitting, verify the Render public hostname resolves correctly:

```bash
curl -I https://hr-policy-bot-web-app.onrender.com/health
```

Expected: HTTP 200. This hostname is the CNAME target.

---

## Proposed Subdomain

```
dnd-rh-hr.alpha.canada.ca
```

- `dnd` — department identifier
- `rh-hr` — bilingual "Ressources humaines / Human Resources"

Alternatives if taken:
- `rh-pol-dnd.alpha.canada.ca`
- `hr-pol-dnd.alpha.canada.ca`

---

## Step 1 — Fork and clone the DNS repo

```bash
# Fork https://github.com/cds-snc/dns via GitHub UI, then:
git clone git@github.com:Kyrinov/dns.git
cd dns
git checkout -b add-dnd-rh-hr-alpha
```

## Step 2 — Create the Terraform file

Create `terraform/dnd-rh-hr.alpha.canada.ca.tf` with this exact content:

```hcl
resource "aws_route53_record" "dnd-rh-hr-alpha-canada-ca-CNAME" {
  zone_id = aws_route53_zone.alpha-canada-ca-public.zone_id
  name    = "dnd-rh-hr.alpha.canada.ca"
  type    = "CNAME"
  records = [
    "hr-policy-bot-web-app.onrender.com"
  ]
  ttl = "300"
}
```

## Step 3 — Format and commit

```bash
make fmt
git add terraform/dnd-rh-hr.alpha.canada.ca.tf
git commit -m "feat: add dnd-rh-hr.alpha.canada.ca CNAME for DND HR policy prototype"
git push -u origin add-dnd-rh-hr-alpha
```

## Step 4 — Open the Pull Request

Submit a PR from `Kyrinov/dns` → `cds-snc/dns`. Use this PR body:

---

> **Request: dnd-rh-hr.alpha.canada.ca**
>
> **Application:** DND HR-Civ Policy Advisory System (pilot prototype)
>
> **Purpose:** Multi-agent AI system that provides HR advisors at DND ADM(HR-Civ) with accurate, referenced guidance on federal civilian HR policy. Orchestrates 8 specialist agents querying 147 authoritative policy instruments (PSEA, CHRA, collective agreements, TBS directives, etc.).
>
> **Record type:** CNAME → `hr-policy-bot-web-app.onrender.com`
>
> **Tech contact:** Charles Humphrey — chumphrey385@gmail.com
>
> **Status:** Pilot PoC — internal stakeholder demos, not public production traffic.

---

## Step 5 — Notify the Platform team

Email `sre-ifs@cds-snc.ca` to flag the PR and confirm eligibility as a DND prototype.

---

## Step 6 — After the PR merges: Add custom domain in Render

1. Open the Render dashboard → **hr-policy-bot-web-app** → **Settings → Custom Domains**
2. Add `dnd-rh-hr.alpha.canada.ca`
3. Render will provision a TLS certificate automatically (Let's Encrypt)

---

## Verification

```bash
# DNS propagation (run after merge, may take up to 5 min)
dig dnd-rh-hr.alpha.canada.ca CNAME

# End-to-end health check
curl -I https://dnd-rh-hr.alpha.canada.ca/health
```

Expected: CNAME → `hr-policy-bot-web-app.onrender.com`, health endpoint returns HTTP 200.
