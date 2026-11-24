import { createFileRoute } from "@tanstack/react-router";
import { InsuranceWorkspace } from "@/components/insurance-workspace";
export const Route = createFileRoute("/documents")({
  head: () => ({
    meta: [
      { title: "Documents | Insurance Intelligence" },
      {
        name: "description",
        content:
          "Documents for the Azerbaijan insurance legal intelligence demonstration workspace.",
      },
      { property: "og:title", content: "Documents | Insurance Intelligence" },
      {
        property: "og:description",
        content: "Explore documents in the insurance intelligence prototype.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => <InsuranceWorkspace view="documents" />,
});
