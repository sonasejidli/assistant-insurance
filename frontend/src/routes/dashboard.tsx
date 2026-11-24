import { createFileRoute } from "@tanstack/react-router";
import { InsuranceWorkspace } from "@/components/insurance-workspace";
export const Route = createFileRoute("/dashboard")({
  head: () => ({
    meta: [
      { title: "Project overview | Insurance Intelligence" },
      {
        name: "description",
        content:
          "Project overview for the Azerbaijan insurance legal intelligence demonstration workspace.",
      },
      { property: "og:title", content: "Project overview | Insurance Intelligence" },
      {
        property: "og:description",
        content: "Explore project overview in the insurance intelligence prototype.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => <InsuranceWorkspace view="dashboard" />,
});
