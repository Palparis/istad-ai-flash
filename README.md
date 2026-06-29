# IstadAi - Audit Flash Maturité IA

Pré-diagnostic gratuit en 10 questions, 5-10 minutes. Scoring 100%
déterministe sur 8 axes, analyse qualitative optionnelle par Claude
(Anthropic) avec garanties anti-training contractuelles, synthèse PDF
immédiate. Lien partageable pour test marché.

## Architecture

```
agent-audit-flash/
├── app.py                  # Streamlit app (4 vues : intro / questionnaire / gate email / résultats)
├── questions_flash.yaml    # 10 questions + ancres CMMI + wording RGPD
├── scoring_flash.py        # Logique scoring (FlashResult dataclass)
├── pdf_flash.py            # PDF synthèse 1 page (reportlab + matplotlib)
├── lead_notifier.py        # Envoi notification email à chaque lead capturé
├── requirements.txt
└── README.md
```

Aucune dépendance à `shared/`. L'analyse LLM (optionnelle, consent-based)
utilise directement le SDK `anthropic` avec une clé API dédiée et un cost
guard local (caps quotidien et mensuel). Module 100% autonome.

## Configuration SMTP (notifications leads)

À chaque audit complété, un mail récapitulatif est envoyé à
`pierre-alain.laval@istada.fr` avec le PDF en pièce jointe. Variables
d'environnement à définir :

```env
# .env (à la racine du monorepo) ou Streamlit Cloud secrets
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=ton.adresse@gmail.com
SMTP_PASSWORD=xxxx-xxxx-xxxx-xxxx     # App password Gmail (16 caractères)
LEAD_NOTIFICATION_TO=pierre-alain.laval@istada.fr
```

### Comment créer un App Password Gmail

1. Active la **2-Step Verification** sur ton compte Google
   → https://myaccount.google.com/security
2. Va sur https://myaccount.google.com/apppasswords
3. Génère un App Password (16 caractères sans espaces)
4. Colle-le dans `SMTP_PASSWORD`

### Sur Streamlit Cloud

Dans l'interface admin de l'app, va dans **Settings → Secrets** et colle :

```toml
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = "587"
SMTP_USER = "ton.adresse@gmail.com"
SMTP_PASSWORD = "xxxx-xxxx-xxxx-xxxx"
LEAD_NOTIFICATION_TO = "pierre-alain.laval@istada.fr"
```

Si SMTP n'est pas configuré (variables absentes), l'app **fonctionne quand
même** mais les leads ne sont pas notifiés (warning visible uniquement dans
les logs serveur). Pratique pour tester en local sans tout configurer.

## Lancer en local

```bash
cd istad-ai/agent-audit-flash
pip install -r requirements.txt
streamlit run app.py
```

L'app se lance sur `http://localhost:8501`.

## Déployer sur Streamlit Cloud (gratuit)

1. Le repo GitHub IstadAi est déjà en place (privé)
2. Aller sur https://share.streamlit.io et connecter le repo
3. Configuration :
   - Repository : `pierre-alain-laval/istad-ai` (ou équivalent)
   - Branch : `main`
   - Main file path : `istad-ai/agent-audit-flash/app.py`
4. Récupérer l'URL générée (ex : `https://istad-ai-flash.streamlit.app/`)
5. Partager le lien aux prospects à tester

## Pipeline utilisateur

1. **Intro** : nom organisation + rôle + case consentement (RGPD pré-cadré)
2. **Questionnaire** : 9 questions scorées (8 axes + 1 transverse) + 1 contextuelle
   - Champ libre optionnel (200 chars max, non scoré, apparaît dans le PDF)
   - Auto-évaluation 5 ancres CMMI (obligatoire, scoré)
3. **Gate email** : prénom + nom + email + téléphone + consentement recontact
   - Email envoyé automatiquement à IstadAi avec PDF en PJ
   - Reply-To préremplie avec l'email du lead (réponse directe possible)
4. **Résultats** : score global + radar + forces/gaps + dissonance + PDF + CTA email

## Cohérence avec l'agent #2 (audit complet)

- Mêmes axes (V/P/D/O/T/A/M/G) - même framework propriétaire IstadAi
- Mêmes ancres CMMI (1 Initial → 5 Optimized)
- Mêmes couleurs niveau (rouge → vert)
- Même style PDF (typographie, footer paginé)

Si un prospect remonte à un audit complet, ses scores flash peuvent servir
de référence N0 (à comparer aux scores extraits des entretiens en N1).

## Garde-fous v0 (minimaux)

- Consentement explicite (case à cocher, pas pré-cochée)
- Pas de capture serveur (tout en `st.session_state`, perdu au refresh)
- Pas d'appel LLM (zéro coût, zéro risque de fuite)
- PDF généré client-side via Streamlit
- Lien partageable directement par mail (pas de landing, pas de SEO)

## Évolutions possibles (v1+)

- Capture email post-résultats pour envoi PDF par email
- Mode "compare with peers" : moyennes sectorielles
- Mode multi-répondants (envoyer le lien à 3-5 dirigeants, agréger les scores)
- Détection dissonance multi-répondants (équivalent du secret sauce de l'agent #2)
- Narration LLM personnalisée du PDF (si engagement observé)

## Coût opérationnel v0

Zéro. Streamlit Cloud gratuit (jusqu'à 1 app/community tier), pas d'API LLM,
pas de stockage, pas de domaine custom.
