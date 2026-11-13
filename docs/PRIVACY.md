# Privacy and responsible deployment

## What CrowdSense does not do
- No face detection, recognition or embeddings
- No person re-identification across cameras or days
- No frames or video stored by the analytics (the optional `--save-video` writes an annotated file **only when you ask**, for debugging; do not enable it in production)
- No personal data in the database

## What it processes
Anonymous bounding boxes and short-lived integer track IDs, held in memory. Only **aggregates** reach disk: counts, densities, wait estimates, alert text.

## Deploying responsibly
1. **Tell people.** Post clear signage that crowd analytics is in use.
2. **Check the law.** Video of people is regulated almost everywhere (for example India's Digital Personal Data Protection Act 2023, GDPR). Aggregated, non-identifying analytics is the low-risk end, but confirm with your legal advisor.
3. **Keep a human in the loop.** Alerts support a duty manager's judgement; they do not replace it.
4. **Do not use it to profile individuals.** The design deliberately makes that hard; do not work around it.
5. **Life safety.** This is not a certified safety system. Keep your existing fire, evacuation and security procedures.
