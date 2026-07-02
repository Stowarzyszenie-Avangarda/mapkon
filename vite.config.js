import { defineConfig } from 'vite';
import { resolve } from 'node:path';

// Front-end lives in web/ (index.html is the entry). The Python data step writes the
// generated map data + logos into public/, which Vite copies verbatim to dist/ (they
// are fetched at runtime by fixed relative URLs, so they must NOT be hashed).
export default defineConfig({
  root: 'web',
  // Relative asset paths so it works from a GitHub Pages project subpath (/<repo>/),
  // a user page, or a custom domain without hardcoding the base.
  base: './',
  publicDir: resolve(__dirname, 'public'),
  build: {
    outDir: resolve(__dirname, 'dist'),
    emptyOutDir: true,
  },
});
