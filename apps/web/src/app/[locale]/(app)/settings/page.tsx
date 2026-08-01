import { redirect } from "@/i18n/navigation";

// Personal, session-bound, and never useful to a crawler.
export const dynamic = "force-dynamic";

/** Settings has no landing of its own; it opens on the account profile. */
export default async function SettingsPage(props: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  redirect({ href: "/settings/profile", locale });
}
