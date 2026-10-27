# SignalProof public demo + portfolio update

This package adds a static **public demo** to the working SignalProof project. It does not replace `app.py`, `performance.py`, or your SQLite history.

The `docs/` folder uses the same dark interface as the local Python application, but all measurements are generated sample data. Visitors can explore the history, load an example performance test, change filters, view reports, and export sample CSVs. It does not connect to or measure their network.

## Add the demo to GitHub

From the SignalProof project on my Mac:

```bash
cd ~/personal_projects/signalproof
unzip -o ~/Downloads/signalproof-public-demo-and-portfolio.zip -d .
python3 -m http.server 8085 --directory docs
```

I can open `http://127.0.0.1:8085/` to preview the static demo. `Control+C` stops the preview. This is independent from the live monitoring app on port 8765.

Once the public demo looks right:

```bash
cd ~/personal_projects/signalproof
# Confirm local data will not be uploaded.
git status --short
git check-ignore measurements.db
python3 tools/update_readme.py
git add docs tools/replace_gradebook.py tools/update_readme.py HOW_TO_PUBLISH.md README.md
git commit -m "Add public SignalProof demo"
git push -u origin main
```

In GitHub: repository **Settings → Pages → Deploy from a branch → main → /docs → Save**.

The expected demo URL after Pages publishes is `https://rayjim28.github.io/signalproof/`. Open it and verify the demo works before adding it to the portfolio. Do not publish the real SQLite database.

## Replace Gradebook in the portfolio

After the public demo is online, run:

```bash
cd ~/personal_projects/portfolio_2
python3 ~/personal_projects/signalproof/tools/replace_gradebook.py \
  ~/personal_projects/portfolio_2 ~/personal_projects/signalproof
npm run build
```

The script replaces **only** the Gradebook entry and copies a SignalProof screenshot into `public/`. It does not delete Gradebook's original source repository or image file.

If the build passes:

```bash
git add src/data/projects.ts public/signalproof-dashboard.png
git commit -m "Replace Gradebook with SignalProof"
git push origin main
```

Vercel will update the portfolio if automatic GitHub deployments are enabled.

## Notes

The screenshot supplied here is from the local SignalProof interface, not an actual measurement of the public demo. The sample measurements and incident times in the demo are deliberately invented and clearly labeled. The real Python app is still needed to test a user's connection.
