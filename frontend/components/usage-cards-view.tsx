"use client";

import { useState, type MouseEvent } from "react";

import { MarkdownContent } from "@/components/markdown-content";
import {
  createUsageCard,
  deleteUsageCard,
  updateUsageCard,
} from "@/lib/api";
import type { UsageCard } from "@/lib/types";

const PUBLIC_USAGE_API_BASE_URL =
  process.env.NEXT_PUBLIC_CONTEXT_ROUTER_API_URL ?? "http://127.0.0.1:8000";

type UsageCardsViewProps = {
  initialCards: UsageCard[];
};

type UsageCardDraft = {
  title: string;
  description: string;
  content_markdown: string;
};

const emptyDraft: UsageCardDraft = {
  title: "",
  description: "",
  content_markdown: "",
};

export function UsageCardsView({ initialCards }: UsageCardsViewProps) {
  const [cards, setCards] = useState(initialCards);
  const [selectedCard, setSelectedCard] = useState<UsageCard | null>(null);
  const [draft, setDraft] = useState<UsageCardDraft>(emptyDraft);
  const [isEditing, setIsEditing] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [visibleEndpointSlug, setVisibleEndpointSlug] = useState<string | null>(null);
  const [copiedEndpointSlug, setCopiedEndpointSlug] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  function openCard(card: UsageCard) {
    setSelectedCard(card);
    setDraft(cardToDraft(card));
    setIsEditing(false);
    setIsCreating(false);
    setMessage("");
  }

  function openNewCard() {
    setSelectedCard(null);
    setDraft(emptyDraft);
    setIsEditing(true);
    setIsCreating(true);
    setMessage("");
  }

  function closeModal() {
    setSelectedCard(null);
    setDraft(emptyDraft);
    setIsEditing(false);
    setIsCreating(false);
    setMessage("");
  }

  async function saveCard() {
    if (!draft.title.trim() || !draft.content_markdown.trim()) {
      setMessage("Title and Markdown content are required.");
      return;
    }

    setIsSaving(true);
    setMessage("");
    try {
      const saved = isCreating
        ? await createUsageCard(draft)
        : await updateUsageCard(selectedCard?.slug ?? "", {
            ...draft,
            sort_order: selectedCard?.sort_order,
          });

      setCards((currentCards) => {
        const withoutSaved = currentCards.filter((card) => card.slug !== saved.slug);
        return [...withoutSaved, saved].sort(compareCards);
      });
      setSelectedCard(saved);
      setDraft(cardToDraft(saved));
      setIsCreating(false);
      setIsEditing(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to save usage card.");
    } finally {
      setIsSaving(false);
    }
  }

  async function removeCard() {
    if (!selectedCard || selectedCard.is_builtin) {
      return;
    }
    const shouldDelete = window.confirm("Delete this usage card?");
    if (!shouldDelete) {
      return;
    }

    setIsSaving(true);
    setMessage("");
    try {
      await deleteUsageCard(selectedCard.slug);
      setCards((currentCards) => currentCards.filter((card) => card.slug !== selectedCard.slug));
      closeModal();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to delete usage card.");
    } finally {
      setIsSaving(false);
    }
  }

  function toggleEndpoint(event: MouseEvent<HTMLButtonElement>, card: UsageCard) {
    event.stopPropagation();
    setCopiedEndpointSlug(null);
    setVisibleEndpointSlug((currentSlug) => (currentSlug === card.slug ? null : card.slug));
  }

  async function copyEndpoint(event: MouseEvent<HTMLButtonElement>, card: UsageCard) {
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(cardEndpoint(card));
      setCopiedEndpointSlug(card.slug);
      setTimeout(() => setCopiedEndpointSlug(null), 1600);
    } catch {
      setCopiedEndpointSlug(null);
    }
  }

  const activeTitle = isCreating ? "New usage card" : selectedCard?.title ?? "";

  return (
    <>
      <section className="section usage-toolbar">
        <button className="button active" onClick={openNewCard} type="button">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14" />
            <path d="M5 12h14" />
          </svg>
          <span>New card</span>
        </button>
      </section>

      <section className="section usage-card-grid">
        {cards.length === 0 ? (
          <div className="panel usage-empty-panel">
            <p className="page-subtitle">No usage cards yet.</p>
            <button className="button" onClick={openNewCard} type="button">
              Create the first card
            </button>
          </div>
        ) : (
          cards.map((card) => (
            <article
              className="panel usage-card"
              key={card.slug}
              onClick={() => openCard(card)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  openCard(card);
                }
              }}
              role="button"
              tabIndex={0}
            >
              <div className="usage-card-header">
                <h3>{card.title}</h3>
                {card.is_builtin ? <span className="badge">Built-in</span> : null}
              </div>
              <p>{card.description || "No description yet."}</p>
              <div className="usage-card-footer">
                <code>{card.slug}</code>
                <button
                  className="button usage-card-api-button"
                  onClick={(event) => toggleEndpoint(event, card)}
                  type="button"
                >
                  API
                </button>
              </div>
              {visibleEndpointSlug === card.slug ? (
                <div className="usage-card-endpoint" onClick={(event) => event.stopPropagation()}>
                  <code>{cardEndpoint(card)}</code>
                  <button
                    className="button usage-card-copy-button"
                    onClick={(event) => void copyEndpoint(event, card)}
                    type="button"
                  >
                    {copiedEndpointSlug === card.slug ? "Copied" : "Copy"}
                  </button>
                </div>
              ) : null}
            </article>
          ))
        )}
      </section>

      {selectedCard || isCreating ? (
        <div className="usage-modal-backdrop" role="presentation">
          <section className="usage-modal" aria-modal="true" role="dialog">
            <header className="usage-modal-header">
              <div>
                <h2>{activeTitle}</h2>
                <p>{isEditing ? "Edit Markdown content." : "Markdown preview."}</p>
              </div>
              <button className="icon-close-button" onClick={closeModal} type="button">
                ×
              </button>
            </header>

            {isEditing ? (
              <div className="usage-edit-form">
                <label>
                  <span>Title</span>
                  <input
                    onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                    value={draft.title}
                  />
                </label>
                <label>
                  <span>Description</span>
                  <input
                    onChange={(event) =>
                      setDraft({ ...draft, description: event.target.value })
                    }
                    value={draft.description}
                  />
                </label>
                <label>
                  <span>Markdown</span>
                  <textarea
                    onChange={(event) =>
                      setDraft({ ...draft, content_markdown: event.target.value })
                    }
                    rows={18}
                    value={draft.content_markdown}
                  />
                </label>
              </div>
            ) : (
              <div className="usage-markdown-panel">
                <MarkdownContent content={selectedCard?.content_markdown ?? ""} />
              </div>
            )}

            {message ? <p className="usage-modal-message">{message}</p> : null}

            <footer className="usage-modal-actions">
              {!isEditing ? (
                <button className="button active" onClick={() => setIsEditing(true)} type="button">
                  Edit
                </button>
              ) : (
                <>
                  <button
                    className="button active"
                    disabled={isSaving}
                    onClick={() => void saveCard()}
                    type="button"
                  >
                    Save
                  </button>
                  <button
                    className="button"
                    disabled={isSaving}
                    onClick={() => {
                      if (selectedCard) {
                        setDraft(cardToDraft(selectedCard));
                        setIsEditing(false);
                        setIsCreating(false);
                        setMessage("");
                      } else {
                        closeModal();
                      }
                    }}
                    type="button"
                  >
                    Cancel
                  </button>
                </>
              )}
              {selectedCard && !selectedCard.is_builtin ? (
                <button
                  className="button usage-danger-button"
                  disabled={isSaving}
                  onClick={() => void removeCard()}
                  type="button"
                >
                  Delete
                </button>
              ) : null}
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}

function cardToDraft(card: UsageCard): UsageCardDraft {
  return {
    title: card.title,
    description: card.description,
    content_markdown: card.content_markdown,
  };
}

function compareCards(left: UsageCard, right: UsageCard) {
  return left.sort_order - right.sort_order || left.title.localeCompare(right.title);
}

function cardEndpoint(card: UsageCard) {
  return `${PUBLIC_USAGE_API_BASE_URL}/api/usage/cards/${encodeURIComponent(card.slug)}`;
}
