export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname.startsWith("/products/")) {
      const assetUrl = new URL(request.url);
      if (!assetUrl.pathname.endsWith(".html")) assetUrl.pathname += ".html";
      // Keep the asset lookup URL free of query parameters so the Assets
      // binding resolves the exact generated file.
      assetUrl.search = "";

      const assetRequest = new Request(assetUrl.toString(), {
        method: "GET",
        headers: request.headers,
      });
      const response = await env.ASSETS.fetch(assetRequest);
      if (response.status === 200) {
        const headers = new Headers(response.headers);
        headers.set("Cache-Control", "no-store, max-age=0");
        return new Response(response.body, {
          status: 200,
          headers,
        });
      }
    }

    return env.ASSETS.fetch(request);
  },
};