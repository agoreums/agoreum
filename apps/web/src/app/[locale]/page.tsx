import { getTranslations, setRequestLocale } from "next-intl/server";

import { AgentTransaction } from "@/components/landing/agent-transaction";
import { DeveloperExperience } from "@/components/landing/developer";
import { Faq } from "@/components/landing/faq";
import { Hero } from "@/components/landing/hero";
import { HowItWorks } from "@/components/landing/how-it-works";
import { MarketplaceShowcase } from "@/components/landing/marketplace-showcase";
import {
  CallToAction,
  CoreFeatures,
  Roadmap,
  SecurityTrust,
  SupportedTechnologies,
  TrustedArchitecture,
} from "@/components/landing/sections";
import { Stats } from "@/components/landing/stats";
import { WebSiteJsonLd } from "@/components/seo/json-ld";
import { locales } from "@/i18n/routing";

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

export default async function HomePage(props: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  const tMeta = await getTranslations("metadata");

  return (
    <>
      <WebSiteJsonLd description={tMeta("description")} />

      <Hero />
      <Stats />
      <TrustedArchitecture />
      <HowItWorks />
      <MarketplaceShowcase />
      <AgentTransaction />
      <CoreFeatures />
      <SecurityTrust />
      <SupportedTechnologies />
      <DeveloperExperience />
      <Roadmap />
      <Faq />
      <CallToAction />
    </>
  );
}
