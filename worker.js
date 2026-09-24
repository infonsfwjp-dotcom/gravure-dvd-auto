export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Product URLs are intentionally extensionless. Serve the corresponding
    // .html asset so browsers receive Content-Type: text/html instead of
    // treating the extensionless asset as a downloadable data file.
    if (
      url.pathname.startsWith("/products/") &&
      !url.pathname.endsWith("/") &&
      !url.pathname.endsWith(".html")
    ) {
      const htmlUrl = new URL(url);
      htmlUrl.pathname += ".html";
      const response = await env.ASSETS.fetch(new Request(htmlUrl, request));
      if (response.status === 200) {
        return response;
      }
    }

    return env.ASSETS.fetch(request);
  },
};
