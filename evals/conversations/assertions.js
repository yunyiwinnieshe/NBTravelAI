const body = pm.response.json();
if (pm.environment.get("record_responses") === "true") {
    console.log("EVAL_RESPONSE " + JSON.stringify({
        request: pm.info.requestName, status: pm.response.code, body
    }));
}
pm.test("HTTP status", () => pm.expect(pm.response.code).to.eql(expected.http_status));
if (pm.response.code === 200) {
    pm.test("Conversation state", () => pm.expect(body.state).to.eql(expected.state));
    pm.test("Assistant text is present", () => pm.expect(body.assistant_message).to.be.a("string").and.not.empty);
    const draft = body.trip_request_draft;
    pm.test("Stable traveler IDs", () => pm.expect(draft.travelers.map(t => t.traveler_id).sort()).to.eql(["traveler_a", "traveler_b"]));
    const normalized = {...draft, travelers: Object.fromEntries(draft.travelers.map(t => [t.traveler_id, t]))};
    const get = (obj, path) => path.split(".").reduce((v, key) => v == null ? undefined : v[key], obj);
    for (const [path, value] of Object.entries(expected.fields || {})) {
        pm.test("Expected " + path, () => {
            const actual = get(normalized, path);
            pm.expect(Array.isArray(actual) ? [...actual].sort() : actual).to.eql(Array.isArray(value) ? [...value].sort() : value);
        });
    }
    for (const path of expected.missing || []) {
        pm.test("Clarify " + path, () => pm.expect(body.missing_fields).to.include(path));
    }
    if (expected.missing_any) {
        pm.test("Clarify ambiguous ownership", () => pm.expect(expected.missing_any.some(p => body.missing_fields.includes(p))).to.eql(true));
    }
    if (expected.unsupported !== undefined) {
        pm.test("Unsupported notice state", () => pm.expect(body.unsupported_requests.length > 0).to.eql(expected.unsupported));
    }
    if (expected.deferred) {
        pm.test("Excluded request recorded", () => pm.expect(body.deferred_requests.length).to.be.above(0));
    }
    pm.test("Question batch limit", () => pm.expect(body.pending_questions.length).to.be.at.most(body.unsupported_requests.length ? 2 : 3));
    pm.test("Recommendation gate", () => {
        if (expected.state === "results") pm.expect(body.recommendations.length).to.be.above(0);
        else pm.expect(body.recommendations).to.eql([]);
    });
    if (expected.preserve_except) {
        pm.test("Unrelated draft fields preserved", () => {
            const before = JSON.parse(pm.collectionVariables.get("previous_draft"));
            const after = JSON.parse(JSON.stringify(normalized));
            const remove = (obj, path) => {
                const keys = path.split("."); const last = keys.pop();
                const parent = keys.reduce((v, k) => v == null ? undefined : v[k], obj);
                if (parent) delete parent[last];
            };
            expected.preserve_except.forEach(path => { remove(before, path); remove(after, path); });
            pm.expect(after).to.eql(before);
        });
    }
    pm.collectionVariables.set("previous_draft", JSON.stringify(normalized));
    pm.collectionVariables.set("session_id", body.session_id);
}
