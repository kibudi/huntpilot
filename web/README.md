# web

The huntpilot dashboard: React 19 + TypeScript + Vite, styled with Tailwind v4.

Two tabs over one API. **Applications** is the pipeline the user keeps by hand — add, search,
filter, sort, and move a job along by clicking its status pill. **Board** is what the sweep found
on company job boards, with one button per row to copy a posting into the pipeline.

All state lives in `App.tsx`; everything under `components/` is presentation. `api.ts` is the only
place that talks to the backend, and there is no client-side store or router.

```sh
npm install
npm run dev      # Vite on 5173, proxying /api to the backend on 8000
npm run build    # tsc -b && vite build
npm run lint     # oxlint
```

The backend has to be running for either tab to load. See the repo root README for the full stack.
