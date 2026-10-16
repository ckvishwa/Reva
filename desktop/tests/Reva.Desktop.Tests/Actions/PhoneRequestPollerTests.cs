using System.Text.Json;
using Reva.Desktop.Actions;
using Reva.Desktop.Settings;

namespace Reva.Desktop.Tests.Actions;

public sealed class PhoneRequestPollerTests
{
    private static string Fixture(string name) =>
        File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "devices", name + ".json"));

    private static PhoneRequests Parse(string fixture) =>
        ActionsApi.ParsePhoneRequests(JsonDocument.Parse(Fixture(fixture)).RootElement)!;

    private static SettingsResult<PhoneRequests> Ok(params PhoneRequest[] items) =>
        SettingsResult<PhoneRequests>.Success(new PhoneRequests(5, items));

    private static PhoneRequest Card(string id) =>
        new(id, "windows.app.close", "awaiting_approval", "Close Calculator? Approve it on screen.", null, "Pixel 8", null);

    // ---------------------------------------------------------------- the real Core's answer

    [Fact]
    public void The_cores_real_inbox_has_a_card_without_an_order_and_an_order_without_a_prompt()
    {
        var inbox = Parse("phone-requests");

        Assert.Equal(2, inbox.Seq);
        var card = inbox.Items[0];
        Assert.Equal(("windows.app.close", "awaiting_approval", "Pixel 8"), (card.Capability, card.Status, card.From));
        Assert.Equal("Close Calculator? Approve it on screen.", card.Prompt);
        Assert.Null(card.Order);
        var order = inbox.Items[1];
        Assert.Equal(("windows.app.open", "granted"), (order.Capability, order.Status));
        Assert.Null(order.Prompt);
        Assert.NotNull(order.Order);
        Assert.Equal("calculator", order.Order!.Args.GetProperty("app_key").GetString());
        Assert.Equal("local", order.Order.TargetDeviceId);
    }

    [Fact]
    public void An_order_is_handed_out_once_so_the_next_answer_has_only_the_waiting_card()
    {
        var again = Parse("phone-requests-card-only");

        var only = Assert.Single(again.Items);
        Assert.Equal("windows.app.close", only.Capability);
        Assert.Null(only.Order);
    }

    [Fact]
    public void An_item_that_cannot_be_read_is_dropped_not_guessed_at()
    {
        var json = """{"seq":3,"items":[{"capability":"windows.app.open"},{"action_id":"ph-1","status":"awaiting_approval","prompt":"p","from":"Pixel 8"}]}""";

        var parsed = ActionsApi.ParsePhoneRequests(JsonDocument.Parse(json).RootElement)!;

        Assert.Equal("ph-1", Assert.Single(parsed.Items).ActionId);
        Assert.Null(ActionsApi.ParsePhoneRequests(JsonDocument.Parse("""{"items":[]}""").RootElement));
        Assert.Null(ActionsApi.ParsePhoneRequests(JsonDocument.Parse("[]").RootElement));
    }

    [Fact]
    public void A_malformed_inbox_item_does_not_stop_valid_requests()
    {
        const string json = """{"seq":3,"items":[null,42,[],{"action_id":"ph-1","status":"awaiting_approval","prompt":"p"}]}""";

        var parsed = ActionsApi.ParsePhoneRequests(JsonDocument.Parse(json).RootElement)!;

        Assert.Equal("ph-1", Assert.Single(parsed.Items).ActionId);
    }

    // ---------------------------------------------------------------- polling

    [Fact]
    public async Task A_waiting_card_is_shown_every_poll_and_closed_when_the_core_stops_listing_it()
    {
        var api = new FakeApi();
        var coordinator = new ActionCoordinator(api, (AppActionExecutor?)null);
        var shown = new List<string>();
        var closed = new List<string>();
        coordinator.CardRequested += c => shown.Add(c.ActionId);
        coordinator.CardClosed += closed.Add;
        var poller = new PhoneRequestPoller(api, coordinator, TimeSpan.FromSeconds(1));
        api.PhoneResponses.Enqueue(Ok(Card("ph-1"), Card("ph-2")));
        api.PhoneResponses.Enqueue(Ok(Card("ph-1")));
        api.PhoneResponses.Enqueue(Ok());

        await poller.PollOnceAsync(0);
        await poller.PollOnceAsync(5);
        await poller.PollOnceAsync(5);

        Assert.Equal(new[] { "ph-1", "ph-2", "ph-1" }, shown);
        Assert.Equal(new[] { "ph-2", "ph-1" }, closed);
    }

    [Fact]
    public async Task The_poll_returns_the_sequence_to_ask_after_and_null_when_the_core_is_unreachable()
    {
        var api = new FakeApi();
        var poller = new PhoneRequestPoller(api, new ActionCoordinator(api, (AppActionExecutor?)null), TimeSpan.FromSeconds(1));
        api.PhoneResponses.Enqueue(Ok());
        api.PhoneResponses.Enqueue(SettingsResult<PhoneRequests>.Failure(new SettingsError("REVA Core is not reachable.")));

        Assert.Equal(5, await poller.PollOnceAsync(0));
        Assert.Null(await poller.PollOnceAsync(5));
    }

    [Fact]
    public async Task One_item_that_throws_does_not_stop_the_next()
    {
        var api = new FakeApi();
        var coordinator = new ActionCoordinator(api, (AppActionExecutor?)null);
        var shown = new List<string>();
        var first = true;
        coordinator.CardRequested += c =>
        {
            if (first)
            {
                first = false;
                throw new InvalidOperationException("a broken card handler");
            }

            shown.Add(c.ActionId);
        };
        var poller = new PhoneRequestPoller(api, coordinator, TimeSpan.FromSeconds(1));
        api.PhoneResponses.Enqueue(Ok(Card("ph-1"), Card("ph-2")));

        await poller.PollOnceAsync(0);

        Assert.Equal(new[] { "ph-2" }, shown);
    }

    [Fact]
    public async Task The_loop_asks_after_the_last_sequence_backs_off_when_the_core_is_down_and_stops_on_cancel()
    {
        var api = new FakeApi();
        var delays = new List<TimeSpan>();
        using var cts = new CancellationTokenSource();
        var poller = new PhoneRequestPoller(
            api,
            new ActionCoordinator(api, (AppActionExecutor?)null),
            TimeSpan.FromSeconds(7),
            (span, _) =>
            {
                delays.Add(span);
                if (delays.Count >= 5)
                {
                    cts.Cancel();
                }

                return Task.CompletedTask;
            });
        api.PhoneResponses.Enqueue(SettingsResult<PhoneRequests>.Failure(new SettingsError("down")));
        api.PhoneResponses.Enqueue(SettingsResult<PhoneRequests>.Failure(new SettingsError("down")));
        api.PhoneResponses.Enqueue(Ok());
        api.PhoneResponses.Enqueue(Ok());

        await poller.RunAsync(cts.Token);

        Assert.Equal(TimeSpan.FromSeconds(1), delays[0]);
        Assert.Equal(TimeSpan.FromSeconds(2), delays[1]);
        Assert.Equal(TimeSpan.FromMilliseconds(250), delays[2]);
        Assert.Equal(new long[] { 0, 0, 0, 5 }, api.PhoneRequestCalls.Take(4).Select(c => c.After).ToArray());
        Assert.All(api.PhoneRequestCalls, c => Assert.Equal(TimeSpan.FromSeconds(7), c.Wait));
    }

    [Fact]
    public async Task The_backoff_is_capped()
    {
        var api = new FakeApi();
        var delays = new List<TimeSpan>();
        using var cts = new CancellationTokenSource();
        var poller = new PhoneRequestPoller(
            api,
            new ActionCoordinator(api, (AppActionExecutor?)null),
            null,
            (span, _) =>
            {
                delays.Add(span);
                if (delays.Count >= 9)
                {
                    cts.Cancel();
                }

                return Task.CompletedTask;
            });
        for (var i = 0; i < 12; i++)
        {
            api.PhoneResponses.Enqueue(SettingsResult<PhoneRequests>.Failure(new SettingsError("down")));
        }

        await poller.RunAsync(cts.Token);

        Assert.True(delays.Max() <= TimeSpan.FromSeconds(30));
        Assert.Equal(TimeSpan.FromSeconds(30), delays.Max());
    }
}
