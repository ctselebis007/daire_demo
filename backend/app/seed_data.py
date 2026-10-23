"""Synthetic tenant configurations and deterministic record generators."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

from faker import Faker

# ---------------------------------------------------------------- vocab

PRACTICE_SKILLS = {
    "cloud": ["aws", "azure", "gcp", "kubernetes", "terraform", "cloud migration", "devops", "serverless", "finops"],
    "data": ["python", "sql", "spark", "databricks", "snowflake", "mongodb", "data engineering", "data governance", "power bi", "tableau"],
    "ai": ["machine learning", "generative ai", "llm engineering", "nlp", "computer vision", "mlops", "rag", "prompt engineering", "vector search"],
    "cyber": ["zero trust", "identity and access management", "siem", "incident response", "cloud security", "grc", "penetration testing"],
    "erp": ["sap s/4hana", "oracle erp", "workday", "servicenow", "salesforce", "dynamics 365"],
    "strategy": ["operating model design", "change management", "m&a integration", "cost transformation", "supply chain strategy", "customer experience"],
    "finance": ["ifrs", "us gaap", "financial planning", "treasury", "tax technology", "regulatory reporting"],
}
LEADERSHIP_SKILLS = ["stakeholder management", "executive presence", "coaching", "negotiation", "storytelling", "agile delivery"]
CERTS = {
    "cloud": ["AWS Solutions Architect", "Azure Solutions Architect", "Google Professional Cloud Architect", "Certified Kubernetes Administrator"],
    "data": ["Databricks Data Engineer", "SnowPro Core", "MongoDB Certified Developer"],
    "ai": ["AWS Machine Learning Specialty", "Azure AI Engineer", "Databricks ML Professional"],
    "cyber": ["CISSP", "CISM", "CEH", "CCSP"],
    "erp": ["SAP S/4HANA Finance", "Salesforce Administrator", "Workday HCM", "ServiceNow CSA"],
    "strategy": ["PMP", "SAFe Agilist", "Prosci Change Practitioner"],
    "finance": ["CPA", "CFA", "ACCA"],
}
INDUSTRIES = ["financial services", "banking", "insurance", "healthcare", "life sciences", "retail", "consumer products",
              "energy", "utilities", "telecommunications", "media", "public sector", "manufacturing", "automotive", "technology"]
LOCATIONS = {
    "US": ["New York", "Chicago", "Austin", "Atlanta", "San Francisco", "Boston"],
    "UK": ["London", "Manchester"],
    "DE": ["Munich", "Frankfurt"],
    "IN": ["Bengaluru", "Hyderabad", "Mumbai"],
    "CA": ["Toronto"],
    "AU": ["Sydney"],
    "SG": ["Singapore"],
    "GR": ["Athens"],
}
LEVELS = [("analyst", 0, 2), ("consultant", 2, 4), ("senior-consultant", 4, 7), ("manager", 7, 10),
          ("senior-manager", 10, 14), ("director", 14, 20), ("partner", 18, 30)]
VERBS = ["led", "delivered", "architected", "scaled", "modernized", "launched", "turned around", "designed"]
PROJECTS = {
    "cloud": ["a 400-application datacenter exit", "a landing zone and platform engineering program", "a containerization roadmap"],
    "data": ["an enterprise lakehouse", "a customer 360 data platform", "a data mesh pilot"],
    "ai": ["a generative AI claims assistant", "a RAG-based knowledge search", "a demand forecasting model"],
    "cyber": ["a zero trust rollout", "a SOC modernization", "an identity consolidation program"],
    "erp": ["an S/4HANA finance transformation", "a global HR platform rollout", "an order-to-cash redesign"],
    "strategy": ["a post-merger integration", "a cost takeout program", "a target operating model redesign"],
    "finance": ["an IFRS 17 implementation", "a close acceleration program", "a treasury system replacement"],
}
CLIENTS = ["global bank", "regional insurer", "top-10 pharma company", "national retailer", "utility provider",
           "telecom operator", "public sector agency", "automotive OEM", "hospital network", "streaming media company"]

LC_TOPICS = {
    "cloud": ["Cloud Architecture", "Kubernetes Operations", "Infrastructure as Code", "Cloud Cost Management"],
    "data": ["Data Engineering Pipelines", "Lakehouse Design", "SQL Analytics", "Data Governance"],
    "ai": ["Generative AI", "RAG Applications", "Prompt Engineering", "MLOps", "Vector Search and Embeddings", "Responsible AI"],
    "cyber": ["Zero Trust Security", "Incident Response", "Cloud Security Posture", "Identity Management"],
    "erp": ["SAP S/4HANA Finance", "Workday Configuration", "ServiceNow Workflows"],
    "strategy": ["Operating Model Design", "Change Leadership", "Business Case Development"],
    "finance": ["IFRS Fundamentals", "Financial Planning and Analysis", "Treasury Management"],
    "leadership": ["Executive Communication", "Coaching for Performance", "Negotiation Skills", "Leading Agile Teams"],
}
LC_PREFIX = ["Introduction to", "Practical", "Advanced", "Hands-on", "Mastering", "Foundations of", "Applied"]
LC_PROVIDERS = ["Deloitte University", "Coursera", "LinkedIn Learning", "AWS Training", "Microsoft Learn", "MongoDB University", "Udemy Business"]
LC_FORMATS = ["virtual", "in-person", "self-paced", "blended"]
LC_LANGS = ["English", "English", "English", "Spanish", "German", "French", "Japanese"]

VS_CATEGORIES = {
    "cloud services": ["cloud migration", "managed kubernetes", "cloud cost optimization", "multi-cloud networking"],
    "cybersecurity": ["managed detection and response", "penetration testing", "identity governance", "cloud security posture"],
    "data and analytics": ["data engineering", "bi dashboards", "data quality", "master data management"],
    "ai solutions": ["llm fine-tuning", "conversational ai", "document intelligence", "computer vision"],
    "managed services": ["service desk", "application maintenance", "infrastructure monitoring", "sre"],
    "hr technology": ["payroll", "talent acquisition", "learning management", "workforce analytics"],
    "logistics": ["freight forwarding", "last-mile delivery", "warehouse automation", "customs brokerage"],
    "marketing services": ["digital campaigns", "seo", "brand strategy", "marketing analytics"],
}
VS_REGIONS = ["NA", "EMEA", "APAC", "LATAM"]
VS_CERTS = ["ISO 27001", "SOC 2 Type II", "ISO 9001", "FedRAMP", "HITRUST", "PCI DSS", "ISO 14001", "CMMI Level 3"]
VS_BANDS = ["<100k", "100k-1M", "1M-10M", ">10M"]


def _iso_days(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


# ---------------------------------------------------------------- tenant configs

def tenant_configs() -> list[dict]:
    return [
        {
            "_id": "talent-match",
            "clientId": "deloitte-consulting",
            "name": "Talent Match",
            "description": "Match consultants to staffing requests.",
            "piiFields": ["email", "phone"],
            "inputSchema": {
                "type": "object",
                "required": ["recordId", "name", "level", "practice", "skills", "summary", "location", "yearsExperience"],
                "properties": {
                    "recordId": {"type": "string"},
                    "name": {"type": "string", "minLength": 1},
                    "email": {"type": "string"},
                    "level": {"enum": [lv[0] for lv in LEVELS]},
                    "practice": {"enum": list(PRACTICE_SKILLS)},
                    "skills": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "certifications": {"type": "array", "items": {"type": "string"}},
                    "industries": {"type": "array", "items": {"type": "string"}},
                    "location": {"type": "object", "required": ["country"], "properties": {"country": {"type": "string"}, "city": {"type": "string"}}},
                    "yearsExperience": {"type": "number", "minimum": 0, "maximum": 50},
                    "availableFrom": {"type": "string"},
                    "rateBand": {"enum": ["A", "B", "C", "D", "E"]},
                    "languages": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string", "minLength": 10},
                },
            },
            "embeddingInputTemplate": (
                "Consultant {{ name }}. Level: {{ level }}. Practice: {{ practice }}. {{ yearsExperience }} years of experience. "
                "Skills: {{ skills | join(', ') }}. Certifications: {{ (certifications or []) | join(', ') or 'none' }}. "
                "Industries: {{ (industries or []) | join(', ') }}. Based in {{ location.city }}, {{ location.country }}. {{ summary }}"
            ),
            "indexConfig": {
                "keywordFields": ["name", "practice", "skills", "certifications", "industries", "summary"],
                "filterFields": [
                    {"path": "metadata.level", "type": "string"},
                    {"path": "metadata.practice", "type": "string"},
                    {"path": "metadata.skills", "type": "string[]"},
                    {"path": "metadata.industries", "type": "string[]"},
                    {"path": "metadata.certifications", "type": "string[]"},
                    {"path": "metadata.location.country", "type": "string"},
                    {"path": "metadata.yearsExperience", "type": "number"},
                    {"path": "metadata.availableFrom", "type": "date"},
                ],
                "vector": {"numCandidatesMultiplier": 15, "exactSearchBelowDocs": 1000},
            },
            "dataPipeline": [
                {"step": "validate"},
                {"step": "normalize", "config": {"lowercase": ["skills", "industries"]}},
                {"step": "embed"},
            ],
            "recommendationPipeline": {
                "topK": 10, "overfetchFactor": 3,
                "fusion": {"method": "rankFusion", "weights": {"vector": 0.7, "text": 0.3}},
                "rerank": {"provider": "voyage", "topN": 30},
                "explanations": {"enabled": True, "provider": "openai", "maxResults": 10},
            },
            "queryConfig": {
                "schema": {
                    "type": "object", "required": ["roleTitle"], "additionalProperties": False,
                    "properties": {
                        "roleTitle": {"type": "string", "minLength": 2, "maxLength": 200},
                        "level": {"type": "string", "maxLength": 50},
                        "requiredSkills": {"type": "array", "items": {"type": "string", "maxLength": 80}, "maxItems": 20},
                        "industry": {"type": "string", "maxLength": 80},
                        "description": {"type": "string", "maxLength": 2000},
                    },
                },
                "serializationTemplate": (
                    "Staffing request for a {% if level %}{{ level }} {% endif %}{{ roleTitle }}"
                    "{% if industry %} in {{ industry }}{% endif %}."
                    "{% if requiredSkills %} Required skills: {{ requiredSkills | join(', ') }}.{% endif %} {{ description or '' }}"
                ),
                "keywordTemplate": "{{ roleTitle }} {{ (requiredSkills or []) | join(' ') }} {{ industry or '' }}",
            },
            "filterConfig": {"allowed": [
                {"field": "metadata.level", "ops": ["eq", "in", "nin"]},
                {"field": "metadata.practice", "ops": ["eq", "in"]},
                {"field": "metadata.skills", "ops": ["eq", "in"]},
                {"field": "metadata.industries", "ops": ["eq", "in"]},
                {"field": "metadata.certifications", "ops": ["eq", "in", "exists"]},
                {"field": "metadata.location.country", "ops": ["eq", "in", "ne"]},
                {"field": "metadata.yearsExperience", "ops": ["gte", "lte", "gt", "lt"]},
                {"field": "metadata.availableFrom", "ops": ["lte", "gte"]},
            ]},
            "sampleQueries": [
                {"label": "AWS migration lead for a bank (US/UK, 8+ yrs)",
                 "query": {"roleTitle": "Cloud migration lead", "level": "senior manager", "requiredSkills": ["aws", "cloud migration", "terraform"],
                           "industry": "banking", "description": "Lead a multi-year core banking workload migration to AWS with a landing zone build-out."},
                 "filters": [{"field": "metadata.yearsExperience", "op": "gte", "value": 8},
                             {"field": "metadata.location.country", "op": "in", "value": ["US", "UK"]}]},
                {"label": "GenAI architect for healthcare (available within 60 days)",
                 "query": {"roleTitle": "Generative AI architect", "requiredSkills": ["generative ai", "rag", "llm engineering", "python"],
                           "industry": "healthcare", "description": "Design a retrieval-augmented clinical documentation assistant."},
                 "filters": [{"field": "metadata.availableFrom", "op": "lte", "value": _iso_days(60)}]},
                {"label": "SAP finance transformation manager in Germany",
                 "query": {"roleTitle": "S/4HANA finance transformation manager", "level": "manager", "requiredSkills": ["sap s/4hana", "ifrs"],
                           "industry": "manufacturing"},
                 "filters": [{"field": "metadata.location.country", "op": "eq", "value": "DE"}]},
            ],
        },
        {
            "_id": "learning-catalog",
            "clientId": "deloitte-university",
            "name": "Learning Catalog",
            "description": "Recommend courses for a learner's development goal.",
            "piiFields": [],
            "inputSchema": {
                "type": "object",
                "required": ["recordId", "title", "description", "topic", "level", "format", "durationHours"],
                "properties": {
                    "recordId": {"type": "string"},
                    "title": {"type": "string", "minLength": 3},
                    "description": {"type": "string", "minLength": 10},
                    "topic": {"enum": list(LC_TOPICS)},
                    "skillsTaught": {"type": "array", "items": {"type": "string"}},
                    "level": {"enum": ["beginner", "intermediate", "advanced"]},
                    "format": {"enum": LC_FORMATS},
                    "durationHours": {"type": "number", "minimum": 0.5, "maximum": 200},
                    "language": {"type": "string"},
                    "rating": {"type": "number", "minimum": 0, "maximum": 5},
                    "provider": {"type": "string"},
                },
            },
            "embeddingInputTemplate": (
                "Course: {{ title }}. Topic: {{ topic }}. Level: {{ level }}. Format: {{ format }}, {{ durationHours }} hours, in {{ language }}. "
                "Skills taught: {{ (skillsTaught or []) | join(', ') }}. Provider: {{ provider }}. {{ description }}"
            ),
            "indexConfig": {
                "keywordFields": ["title", "topic", "skillsTaught", "provider", "description"],
                "filterFields": [
                    {"path": "metadata.topic", "type": "string"},
                    {"path": "metadata.level", "type": "string"},
                    {"path": "metadata.format", "type": "string"},
                    {"path": "metadata.language", "type": "string"},
                    {"path": "metadata.provider", "type": "string"},
                    {"path": "metadata.skillsTaught", "type": "string[]"},
                    {"path": "metadata.durationHours", "type": "number"},
                    {"path": "metadata.rating", "type": "number"},
                ],
                "vector": {"numCandidatesMultiplier": 15, "exactSearchBelowDocs": 1000},
            },
            "dataPipeline": [{"step": "validate"}, {"step": "normalize", "config": {"lowercase": ["skillsTaught"]}}, {"step": "embed"}],
            "recommendationPipeline": {
                "topK": 8, "overfetchFactor": 3,
                "fusion": {"method": "rankFusion", "weights": {"vector": 0.6, "text": 0.4}},
                "rerank": {"provider": "voyage", "topN": 24},
                "explanations": {"enabled": True, "provider": "openai", "maxResults": 8},
            },
            "queryConfig": {
                "schema": {
                    "type": "object", "required": ["goal"], "additionalProperties": False,
                    "properties": {
                        "goal": {"type": "string", "minLength": 3, "maxLength": 500},
                        "skills": {"type": "array", "items": {"type": "string", "maxLength": 80}, "maxItems": 20},
                        "level": {"type": "string", "maxLength": 30},
                    },
                },
                "serializationTemplate": (
                    "Learner goal: {{ goal }}.{% if skills %} Wants to build skills in {{ skills | join(', ') }}.{% endif %}"
                    "{% if level %} Preferred level: {{ level }}.{% endif %}"
                ),
                "keywordTemplate": "{{ goal }} {{ (skills or []) | join(' ') }}",
            },
            "filterConfig": {"allowed": [
                {"field": "metadata.topic", "ops": ["eq", "in"]},
                {"field": "metadata.level", "ops": ["eq", "in"]},
                {"field": "metadata.format", "ops": ["eq", "in", "ne"]},
                {"field": "metadata.language", "ops": ["eq", "in"]},
                {"field": "metadata.provider", "ops": ["eq", "in"]},
                {"field": "metadata.skillsTaught", "ops": ["eq", "in"]},
                {"field": "metadata.durationHours", "ops": ["lte", "gte"]},
                {"field": "metadata.rating", "ops": ["gte"]},
            ]},
            "sampleQueries": [
                {"label": "Get productive with GenAI in under 8 hours (virtual/self-paced)",
                 "query": {"goal": "Become productive building generative AI and RAG prototypes for clients", "skills": ["generative ai", "rag"], "level": "intermediate"},
                 "filters": [{"field": "metadata.durationHours", "op": "lte", "value": 8},
                             {"field": "metadata.format", "op": "in", "value": ["virtual", "self-paced"]}]},
                {"label": "Executive communication, highly rated",
                 "query": {"goal": "Improve executive presence and storytelling with C-suite clients"},
                 "filters": [{"field": "metadata.rating", "op": "gte", "value": 4.2}]},
            ],
        },
        {
            "_id": "vendor-sourcing",
            "clientId": "deloitte-procurement",
            "name": "Vendor Sourcing",
            "description": "Recommend suppliers for a sourcing need.",
            "piiFields": ["contactEmail"],
            "inputSchema": {
                "type": "object",
                "required": ["recordId", "vendorName", "category", "capabilities", "regions", "description"],
                "properties": {
                    "recordId": {"type": "string"},
                    "vendorName": {"type": "string"},
                    "contactEmail": {"type": "string"},
                    "category": {"enum": list(VS_CATEGORIES)},
                    "capabilities": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "regions": {"type": "array", "items": {"enum": VS_REGIONS}, "minItems": 1},
                    "certifications": {"type": "array", "items": {"type": "string"}},
                    "diversityOwned": {"type": "boolean"},
                    "rating": {"type": "number", "minimum": 0, "maximum": 5},
                    "contractValueBand": {"enum": VS_BANDS},
                    "foundedYear": {"type": "integer"},
                    "employees": {"type": "integer"},
                    "description": {"type": "string", "minLength": 10},
                },
            },
            "embeddingInputTemplate": (
                "Vendor {{ vendorName }}. Category: {{ category }}. Capabilities: {{ capabilities | join(', ') }}. "
                "Regions served: {{ regions | join(', ') }}. Certifications: {{ (certifications or []) | join(', ') or 'none' }}. "
                "{{ employees }} employees, founded {{ foundedYear }}. {{ description }}"
            ),
            "indexConfig": {
                "keywordFields": ["vendorName", "category", "capabilities", "certifications", "description"],
                "filterFields": [
                    {"path": "metadata.category", "type": "string"},
                    {"path": "metadata.capabilities", "type": "string[]"},
                    {"path": "metadata.regions", "type": "string[]"},
                    {"path": "metadata.certifications", "type": "string[]"},
                    {"path": "metadata.diversityOwned", "type": "boolean"},
                    {"path": "metadata.rating", "type": "number"},
                    {"path": "metadata.contractValueBand", "type": "string"},
                ],
                "vector": {"numCandidatesMultiplier": 15, "exactSearchBelowDocs": 1000},
            },
            "dataPipeline": [{"step": "validate"}, {"step": "embed"}],
            "recommendationPipeline": {
                "topK": 10, "overfetchFactor": 3,
                "fusion": {"method": "rankFusion", "weights": {"vector": 0.5, "text": 0.5}},
                "rerank": {"provider": "voyage", "topN": 30},
                "explanations": {"enabled": True, "provider": "openai", "maxResults": 10},
            },
            "queryConfig": {
                "schema": {
                    "type": "object", "required": ["need"], "additionalProperties": False,
                    "properties": {
                        "need": {"type": "string", "minLength": 3, "maxLength": 1000},
                        "capabilities": {"type": "array", "items": {"type": "string", "maxLength": 80}, "maxItems": 20},
                        "region": {"type": "string", "maxLength": 20},
                    },
                },
                "serializationTemplate": (
                    "Sourcing need: {{ need }}.{% if capabilities %} Capabilities required: {{ capabilities | join(', ') }}.{% endif %}"
                    "{% if region %} Region: {{ region }}.{% endif %}"
                ),
                "keywordTemplate": "{{ need }} {{ (capabilities or []) | join(' ') }}",
            },
            "filterConfig": {"allowed": [
                {"field": "metadata.category", "ops": ["eq", "in"]},
                {"field": "metadata.capabilities", "ops": ["eq", "in"]},
                {"field": "metadata.regions", "ops": ["eq", "in"]},
                {"field": "metadata.certifications", "ops": ["eq", "in"]},
                {"field": "metadata.diversityOwned", "ops": ["eq"]},
                {"field": "metadata.rating", "ops": ["gte"]},
                {"field": "metadata.contractValueBand", "ops": ["eq", "in"]},
            ]},
            "sampleQueries": [
                {"label": "SOC 2 certified cloud security partner in EMEA",
                 "query": {"need": "Partner to run 24x7 managed detection and response for a hybrid cloud estate", "capabilities": ["managed detection and response"], "region": "EMEA"},
                 "filters": [{"field": "metadata.regions", "op": "eq", "value": "EMEA"},
                             {"field": "metadata.certifications", "op": "eq", "value": "SOC 2 Type II"}]},
                {"label": "Diversity-owned AI document intelligence vendor",
                 "query": {"need": "Automate invoice and contract extraction with document intelligence", "capabilities": ["document intelligence"]},
                 "filters": [{"field": "metadata.diversityOwned", "op": "eq", "value": True}]},
            ],
        },
    ]


# ---------------------------------------------------------------- record generators

def _talent(n: int, rng: random.Random, fake: Faker) -> list[dict]:
    out = []
    for i in range(1, n + 1):
        practice = rng.choice(list(PRACTICE_SKILLS))
        level, lo, hi = rng.choices(LEVELS, weights=[14, 22, 22, 18, 12, 8, 4])[0]
        yrs = rng.randint(lo, hi)
        own = PRACTICE_SKILLS[practice]
        other = PRACTICE_SKILLS[rng.choice([p for p in PRACTICE_SKILLS if p != practice])]
        skills = rng.sample(own, k=min(len(own), rng.randint(3, 6))) + rng.sample(other, k=rng.randint(0, 2))
        if level in ("manager", "senior-manager", "director", "partner"):
            skills += rng.sample(LEADERSHIP_SKILLS, k=rng.randint(1, 2))
        certs = rng.sample(CERTS[practice], k=rng.randint(0, min(2, len(CERTS[practice]))))
        industries = rng.sample(INDUSTRIES, k=rng.randint(1, 3))
        country = rng.choices(list(LOCATIONS), weights=[35, 12, 8, 20, 6, 5, 4, 3])[0]
        name = fake.name()
        project = rng.choice(PROJECTS[practice])
        summary = (
            f"{name.split()[0]} is a {level.replace('-', ' ')} in the {practice} practice with {yrs} years of experience across "
            f"{' and '.join(industries[:2])}. Recently {rng.choice(VERBS)} {project} for a {rng.choice(CLIENTS)}. "
            f"Deep expertise in {', '.join(skills[:3])}."
        )
        out.append({
            "recordId": f"TM-{i:05d}",
            "name": name,
            "email": f"{name.lower().replace(' ', '.').replace(chr(39), '')}@example.com",
            "level": level,
            "practice": practice,
            "skills": skills,
            "certifications": certs,
            "industries": industries,
            "location": {"country": country, "city": rng.choice(LOCATIONS[country])},
            "yearsExperience": yrs,
            "availableFrom": _iso_days(rng.randint(-30, 150)),
            "rateBand": "ABCDE"[min(4, LEVELS.index((level, lo, hi)) * 5 // len(LEVELS))],
            "languages": ["English"] + rng.sample(["Spanish", "German", "French", "Hindi", "Greek", "Mandarin"], k=rng.randint(0, 2)),
            "summary": summary,
        })
    return out


def _learning(n: int, rng: random.Random, fake: Faker) -> list[dict]:
    out = []
    for i in range(1, n + 1):
        topic = rng.choice(list(LC_TOPICS))
        subject = rng.choice(LC_TOPICS[topic])
        level = rng.choice(["beginner", "intermediate", "advanced"])
        prefix = rng.choice(LC_PREFIX)
        pool = PRACTICE_SKILLS.get(topic, LEADERSHIP_SKILLS)
        skills = rng.sample(pool, k=min(len(pool), rng.randint(2, 4)))
        fmt = rng.choice(LC_FORMATS)
        hours = rng.choice([1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 40])
        provider = rng.choice(LC_PROVIDERS)
        desc = (
            f"A {level} {fmt} course on {subject.lower()}. Participants learn {', '.join(skills)} through "
            f"{rng.choice(['case studies', 'guided labs', 'team simulations', 'real client scenarios', 'interactive workshops'])} "
            f"and {rng.choice(['a capstone project', 'peer reviews', 'expert-led Q&A', 'graded assessments'])}. "
            f"{fake.sentence(nb_words=12)}"
        )
        out.append({
            "recordId": f"LC-{i:05d}",
            "title": f"{prefix} {subject}" + (f" ({rng.choice(['2026 Edition', 'Bootcamp', 'Masterclass', 'Essentials'])})" if rng.random() < 0.4 else ""),
            "description": desc,
            "topic": topic,
            "skillsTaught": skills,
            "level": level,
            "format": fmt,
            "durationHours": hours,
            "language": rng.choice(LC_LANGS),
            "rating": round(rng.uniform(3.0, 5.0), 1),
            "provider": provider,
        })
    return out


def _vendor(n: int, rng: random.Random, fake: Faker) -> list[dict]:
    out = []
    for i in range(1, n + 1):
        category = rng.choice(list(VS_CATEGORIES))
        caps = rng.sample(VS_CATEGORIES[category], k=rng.randint(2, 4))
        regions = rng.sample(VS_REGIONS, k=rng.randint(1, 3))
        certs = rng.sample(VS_CERTS, k=rng.randint(0, 3))
        name = fake.company()
        employees = rng.choice([25, 60, 150, 400, 1200, 5000, 20000])
        founded = rng.randint(1985, 2023)
        desc = (
            f"{name} is a {category} provider specializing in {', '.join(caps)}. "
            f"Serves clients in {', '.join(regions)} with a focus on {rng.choice(INDUSTRIES)} and {rng.choice(INDUSTRIES)}. "
            f"{fake.catch_phrase()}."
        )
        out.append({
            "recordId": f"VS-{i:05d}",
            "vendorName": name,
            "contactEmail": fake.company_email(),
            "category": category,
            "capabilities": caps,
            "regions": regions,
            "certifications": certs,
            "diversityOwned": rng.random() < 0.18,
            "rating": round(rng.uniform(2.5, 5.0), 1),
            "contractValueBand": rng.choice(VS_BANDS),
            "foundedYear": founded,
            "employees": employees,
            "description": desc,
        })
    return out


GENERATORS = {"talent-match": _talent, "learning-catalog": _learning, "vendor-sourcing": _vendor}


def generate_records(tenant_id: str, n: int, seed: int = 42) -> list[dict]:
    rng = random.Random(f"{tenant_id}:{seed}")
    fake = Faker()
    fake.seed_instance(f"{tenant_id}:{seed}")
    return GENERATORS[tenant_id](n, rng, fake)


def generate_feedback(tenant_id: str, records: list[dict], n: int, seed: int = 42) -> list[dict]:
    rng = random.Random(f"fb:{tenant_id}:{seed}")
    now = datetime.now(UTC)
    out = []
    for i in range(n):
        r = rng.choice(records)
        position = rng.randint(1, 10)
        overlap = round(rng.random(), 3)
        sim = round(0.55 + 0.4 * rng.random(), 4)
        success = max(0.0, min(1.0, 0.45 * overlap + 0.35 * sim + 0.2 * (1 - position / 10) + rng.gauss(0, 0.08)))
        clicked = success > 0.45 or rng.random() < 0.1
        out.append({
            "tenantId": tenant_id,
            "requestId": f"req-seed-{tenant_id[:2]}-{i // 5:06d}",
            "recordId": r["recordId"],
            "userId": f"u-{rng.randint(1, 400):04d}",
            "feedbackType": rng.choice(["selection", "rating", "dismiss"]) if clicked else "dismiss",
            "successScore": round(success, 4),
            "userRating": round(1 + 4 * success, 2) if rng.random() < 0.4 else None,
            "requestFeatures": {"queryLength": rng.randint(5, 60), "filtersApplied": rng.randint(0, 3)},
            "candidateFeatures": {k: v for k, v in r.items() if k in ("level", "yearsExperience", "topic", "rating", "category", "durationHours")},
            "attributeScores": {"overlap": overlap},
            "interaction": {"clicked": clicked, "viewed": clicked or rng.random() < 0.5,
                            "viewDurationSeconds": rng.randint(3, 180) if clicked else 0, "position": position},
            "embeddingSimilarity": sim,
            "createdAt": now - timedelta(days=rng.uniform(0, 90)),
            "seed": True,
        })
    return out


def generate_audits(tenant_ids: list[str], n: int, seed: int = 42) -> list[dict]:
    rng = random.Random(f"audit:{seed}")
    now = datetime.now(UTC)
    out = []
    for i in range(n):
        tid = rng.choice(tenant_ids)
        status = rng.choices([200, 400, 500], weights=[94, 5, 1])[0]
        total = round(rng.uniform(250, 2500), 1)
        out.append({
            "_id": f"seed-audit-{i:06d}",
            "requestId": f"req-seed-audit-{i:06d}",
            "tenantId": tid,
            "endpoint": f"/v1/tenants/{tid}/recommendations",
            "httpMethod": "POST",
            "httpStatusCode": status,
            "sanitizedRequest": {"query": {"note": "synthetic"}, "filters": []},
            "apiResponse": {"results": []} if status == 200 else None,
            "timingsMs": {"embed": round(rng.uniform(20, 90), 1), "hybridSearch": round(rng.uniform(15, 120), 1), "total": total},
            "error": None if status == 200 else {"code": "INVALID_QUERY" if status == 400 else "InternalError", "message": "synthetic"},
            "createdAt": now - timedelta(days=rng.uniform(0, 120)),
            "seed": True,
        })
    return out
