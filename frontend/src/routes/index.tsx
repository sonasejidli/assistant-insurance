import { createFileRoute } from "@tanstack/react-router";
import { InsuranceWorkspace } from "@/components/insurance-workspace";
export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "AI Assistant | Insurance Intelligence" },
      {
        name: "description",
        content:
          "Explore Azerbaijani insurance legislation with cited, simulated legal explanations.",
      },
      { property: "og:title", content: "AI Assistant | Insurance Intelligence" },
      {
        property: "og:description",
        content:
          "A demonstration legal intelligence workspace for Azerbaijani insurance legislation.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => <InsuranceWorkspace />,
});
