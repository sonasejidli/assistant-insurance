import { createFileRoute } from "@tanstack/react-router";
import { InsuranceWorkspace } from "@/components/insurance-workspace";
export const Route = createFileRoute("/evaluation")({
  head: () => ({
    meta: [
      { title: "Evaluation | Insurance Intelligence" },
      {
        name: "description",
        content:
          "Evaluation for the Azerbaijan insurance legal intelligence demonstration workspace.",
      },
      { property: "og:title", content: "Evaluation | Insurance Intelligence" },
      {
        property: "og:description",
        content: "Explore evaluation in the insurance intelligence prototype.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => <InsuranceWorkspace view="evaluation" />,
});
