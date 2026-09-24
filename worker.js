export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const ASSET_VERSION = "2026-09-25-lcdv41448-fix1";

    // Product detail pages must always resolve to the generated HTML asset.
    // The version query prevents an older edge-cached asset from masking a
    // freshly generated page after deployment.
    if (url.pathname.startsWith("/products/")) {
      const htmlUrl = new URL(url);
      if (!htmlUrl.pathname.endsWith(".html")) {
        htmlUrl.pathname += ".html";
      }
      htmlUrl.searchParams.set("_asset_version", ASSET_VERSION);

      const response = await env.ASSETS.fetch(new Request(htmlUrl, request));
      if (response.status === 200) {
        const headers = new Headers(response.headers);
        headers.set("Cache-Control", "no-store, max-age=0");
        return new Response(response.body, {
          status: response.status,
          statusText: response.statusText,
          headers,
        });
      }
    }

    return env.ASSETS.fetch(request);
  },
};
