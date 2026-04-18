# Auth-Gated App Testing Playbook

## Step 1: Create Test User & Session

```bash
mongosh --eval "
use('quantro_os');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  user_id: userId,  // Custom UUID field (MongoDB's _id is separate/internal)
  email: 'test.user.' + Date.now() + '@example.com',
  name: 'Test User',
  picture: 'https://via.placeholder.com/150',
  created_at: new Date()
});
db.user_sessions.insertOne({
  user_id: userId,  // Must match user.user_id exactly
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000),
  created_at: new Date()
});
print('Session token: ' + sessionToken);
print('User ID: ' + userId);
"
```

## Step 2: Test Backend API

```bash
# Test auth endpoint
curl -X GET "https://quantro-os.preview.emergentagent.com/api/auth/me" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"

# Test protected endpoints with workspace
curl -X GET "https://quantro-os.preview.emergentagent.com/api/inbox" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "X-Workspace-Id: YOUR_WORKSPACE_ID"

curl -X POST "https://quantro-os.preview.emergentagent.com/api/contacts" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "X-Workspace-Id: YOUR_WORKSPACE_ID" \
  -d '{"name": "Test Contact", "email": "test@example.com"}'
```

## Step 3: Browser Testing

```javascript
// Set cookie and navigate
await page.context().addCookies([{
    "name": "session_token",
    "value": "YOUR_SESSION_TOKEN",
    "domain": "quantro-os.preview.emergentagent.com",
    "path": "/",
    "httpOnly": true,
    "secure": true,
    "sameSite": "None"
}]);
await page.goto("https://quantro-os.preview.emergentagent.com");
```

## Quick Debug

```bash
# Check data format
mongosh --eval "
use('quantro_os');
db.users.find().limit(2).pretty();
db.user_sessions.find().limit(2).pretty();
db.workspace_members.find().limit(2).pretty();
"

# Clean test data
mongosh --eval "
use('quantro_os');
db.users.deleteMany({email: /test\.user\./});
db.user_sessions.deleteMany({session_token: /test_session/});
"
```

## Checklist

- [ ] User document has user_id field (custom UUID, MongoDB's _id is separate)
- [ ] Session user_id matches user's user_id exactly
- [ ] All queries use `{"_id": 0}` projection to exclude MongoDB's _id
- [ ] Backend queries use user_id (not _id or id)
- [ ] API returns user data with user_id field (not 401/404)
- [ ] Browser loads dashboard (not login page)
- [ ] Workspace context is properly set via X-Workspace-Id header or cookie
- [ ] RBAC permissions are enforced correctly

## Success Indicators

✅ /api/auth/me returns user data  
✅ Dashboard loads without redirect  
✅ Workspace switcher shows available workspaces  
✅ CRUD operations work with workspace scoping  
✅ Unauthorized actions return 403  

## Failure Indicators

❌ "User not found" errors  
❌ 401 Unauthorized responses  
❌ Redirect to login page  
❌ Cross-workspace data leakage  
❌ Missing RBAC enforcement  

## RBAC Testing Matrix

Test with different roles (Owner/Admin/Manager/Operator/Agent):

| Action | Owner | Admin | Manager | Operator | Agent |
|--------|-------|-------|---------|----------|-------|
| Create workspace | ✅ | ❌ | ❌ | ❌ | ❌ |
| Invite users | ✅ | ✅ | ❌ | ❌ | ❌ |
| Manage policies | ✅ | ✅ | ❌ | ❌ | ❌ |
| Inbox triage | ✅ | ✅ | ✅ | ✅ | ❌ |
| Manual override | ✅ | ✅ | ✅ | ✅ | ❌ |
| CRM updates | ✅ | ✅ | ✅ | ✅ | ❌ |
| View audit logs | ✅ | ✅ | ❌ | ❌ | ❌ |
| View assigned items | ✅ | ✅ | ✅ | ✅ | ✅ |
