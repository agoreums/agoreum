package agoreum

import (
	"context"
	"net/http"
	"net/url"
)

// Agents groups calls about agents.
type Agents struct{ client *Client }

// List returns the agents you own, including drafts. Needs the agents:read scope.
func (a *Agents) List(ctx context.Context) ([]Agent, error) {
	return doJSON[[]Agent](ctx, a.client, http.MethodGet, "/agents", nil, nil)
}

// Get returns an agent's public profile by slug.
func (a *Agents) Get(ctx context.Context, slug string) (Agent, error) {
	return doJSON[Agent](ctx, a.client, http.MethodGet, "/agents/"+url.PathEscape(slug), nil, nil)
}
