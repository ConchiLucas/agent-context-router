import { UsageCardsView } from "@/components/usage-cards-view";
import { getUsageCards } from "@/lib/api";

export default async function UsagePage() {
  const result = await Promise.allSettled([getUsageCards()]);
  const cards = result[0].status === "fulfilled" ? result[0].value.cards : [];

  return <UsageCardsView initialCards={cards} />;
}
