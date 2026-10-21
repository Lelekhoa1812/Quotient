import assert from "node:assert/strict";
import test from "node:test";
import { apiBase, apiMcpUrl, httpMcpUrl, httpsMcpUrl, localHost, STAGING_HTTPS_MCP_URL, STAGING_HTTP_MCP_URL } from "@/lib/origin";

test("a loopback page keeps the local API and any other host uses that page", () => {
  assert.equal(localHost("localhost"), true);
  assert.equal(apiBase({ hostname: "127.0.0.1", origin: "http://127.0.0.1:3000" }), "http://127.0.0.1:8080");
  assert.equal(apiBase(null), "http://127.0.0.1:8080");
  const deployed = { hostname: "axion-meeting-staging-315925467.ap-southeast-2.elb.amazonaws.com", origin: "http://axion-meeting-staging-315925467.ap-southeast-2.elb.amazonaws.com" };
  assert.equal(apiBase(deployed), deployed.origin);
  assert.equal(apiMcpUrl(deployed), `${deployed.origin}/mcp`);

  // Dual endpoint resolution
  assert.equal(httpsMcpUrl(deployed), STAGING_HTTPS_MCP_URL);
  assert.equal(httpMcpUrl(deployed), STAGING_HTTP_MCP_URL);
  assert.equal(httpMcpUrl({ hostname: "localhost", origin: "http://localhost:3000" }), "http://127.0.0.1:8080/mcp");
  assert.equal(httpsMcpUrl({ hostname: "d13b140h08qjom.cloudfront.net", origin: "https://d13b140h08qjom.cloudfront.net" }), "https://d13b140h08qjom.cloudfront.net/mcp");
});
