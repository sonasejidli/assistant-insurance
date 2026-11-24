import { createFileRoute } from "@tanstack/react-router";
import { InsuranceWorkspace } from "@/components/insurance-workspace";
export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings | Insurance Intelligence" },
      {
        name: "description",
        content:
          "Settings for the Azerbaijan insurance legal intelligence demonstration workspace.",
      },
      { property: "og:title", content: "Settings | Insurance Intelligence" },
      {
        property: "og:description",
        content: "Explore settings in the insurance intelligence prototype.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => <InsuranceWorkspace view="settings" />,
});
