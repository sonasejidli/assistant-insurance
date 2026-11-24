import { createFileRoute } from "@tanstack/react-router";
import { InsuranceWorkspace } from "@/components/insurance-workspace";
export const Route = createFileRoute("/analytics")({
  head: () => ({
    meta: [
      { title: "Analytics | Insurance Intelligence" },
      {
        name: "description",
        content:
          "Analytics for the Azerbaijan insurance legal intelligence demonstration workspace.",
      },
      { property: "og:title", content: "Analytics | Insurance Intelligence" },
      {
        property: "og:description",
        content: "Explore analytics in the insurance intelligence prototype.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => <InsuranceWorkspace view="analytics" />,
});
