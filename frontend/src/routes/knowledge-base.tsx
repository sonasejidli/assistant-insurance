import { createFileRoute } from "@tanstack/react-router";
import { InsuranceWorkspace } from "@/components/insurance-workspace";
export const Route = createFileRoute("/knowledge-base")({
  head: () => ({
    meta: [
      { title: "Knowledge Base | Insurance Intelligence" },
      {
        name: "description",
        content:
          "Knowledge Base for the Azerbaijan insurance legal intelligence demonstration workspace.",
      },
      { property: "og:title", content: "Knowledge Base | Insurance Intelligence" },
      {
        property: "og:description",
        content: "Explore knowledge base in the insurance intelligence prototype.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => <InsuranceWorkspace view="knowledge" />,
});
