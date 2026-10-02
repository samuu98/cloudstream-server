package it.zerotituli.server;

import android.app.Activity;
import android.util.Log;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

/** REST adapter injected into an unminified CloudStream APK. No replacement API stubs. */
public final class ServerBridge {
    private static volatile Activity activity;
    private static boolean started;
    private static final Object mutations = new Object();
    private static final ThreadPoolExecutor workers = new ThreadPoolExecutor(4, 4, 0,
        TimeUnit.SECONDS, new ArrayBlockingQueue<Runnable>(16));

    public static synchronized void start(Activity current) {
        activity = current;
        current.getWindow().addFlags(128); // Keep WebView and plugins in a foreground activity.
        if (started) return;
        started = true;
        new Thread(() -> {
            try (ServerSocket server = new ServerSocket(18181, 16, InetAddress.getByName("127.0.0.1"))) {
                while (true) {
                    Socket client = server.accept();
                    try { workers.execute(() -> handle(client)); }
                    catch (RejectedExecutionException busy) { client.close(); }
                }
            } catch (Exception e) { started = false; Log.e("CS3Server", "HTTP bridge stopped", e); }
        }, "cs3-http").start();
    }

    private static Class<?> cls(String name) throws Exception { return Class.forName(name); }
    private static Object singleton(String name) throws Exception { return cls(name).getField("INSTANCE").get(null); }
    private static Method method(Object target, String name, Object... args) throws Exception {
        outer: for (Method m : target.getClass().getMethods()) {
            if (!m.getName().equals(name) || m.getParameterTypes().length != args.length) continue;
            Class<?>[] types = m.getParameterTypes();
            for (int i = 0; i < args.length; i++) {
                Class<?> t = types[i];
                if (t == int.class) t = Integer.class;
                if (t == boolean.class) t = Boolean.class;
                if (args[i] != null && !t.isInstance(args[i])) continue outer;
            }
            return m;
        }
        throw new NoSuchMethodException(target.getClass().getName() + "." + name);
    }
    private static Object call(Object target, String name, Object... args) throws Exception {
        return method(target, name, args).invoke(target, args);
    }
    private static Object property(Object target, String name) throws Exception {
        return call(target, "get" + Character.toUpperCase(name.charAt(0)) + name.substring(1));
    }
    private static Object suspend(Object target, String name, Object... args) throws Exception {
        Class<?> continuation = cls("kotlin.coroutines.Continuation");
        CountDownLatch done = new CountDownLatch(1);
        Object[] result = new Object[1];
        Object callback = java.lang.reflect.Proxy.newProxyInstance(continuation.getClassLoader(), new Class<?>[]{continuation}, (p,m,a) -> {
            if (m.getName().equals("getContext")) return singleton("kotlin.coroutines.EmptyCoroutineContext");
            if (m.getName().equals("resumeWith")) { result[0] = a[0]; done.countDown(); return null; }
            if (m.getName().equals("toString")) return "ServerContinuation";
            if (m.getName().equals("hashCode")) return System.identityHashCode(p);
            if (m.getName().equals("equals")) return p == a[0];
            return null;
        });
        Object[] params = Arrays.copyOf(args, args.length + 1);
        params[args.length] = callback;
        Object immediate = call(target, name, params);
        Object suspended = Enum.valueOf((Class)cls("kotlin.coroutines.intrinsics.CoroutineSingletons"), "COROUTINE_SUSPENDED");
        if (immediate != suspended) return immediate;
        if (!done.await(150, TimeUnit.SECONDS)) throw new TimeoutException("Provider timeout (150s)");
        cls("kotlin.ResultKt").getMethod("throwOnFailure", Object.class).invoke(null, result[0]);
        return result[0];
    }
    private static Object function(List<Object> output) throws Exception {
        Class<?> fn = cls("kotlin.jvm.functions.Function1");
        return java.lang.reflect.Proxy.newProxyInstance(fn.getClassLoader(), new Class<?>[]{fn}, (p,m,a) -> {
            if (m.getName().equals("invoke")) { synchronized(output) { output.add(a[0]); } return singleton("kotlin.Unit"); }
            if (m.getName().equals("toString")) return "ServerCallback";
            return null;
        });
    }
    private static String json(Object value) throws Exception {
        if (value == null) return "null";
        if (value instanceof JSONObject || value instanceof JSONArray) return value.toString();
        Object mapper = cls("com.lagradost.cloudstream3.MainAPIKt").getMethod("getMapper").invoke(null);
        return (String) call(mapper, "writeValueAsString", value);
    }
    private static List<?> providers() throws Exception {
        Object list = property(singleton("com.lagradost.cloudstream3.APIHolder"), "allProviders");
        Map<String,Object> unique = new LinkedHashMap<>();
        synchronized(list) { for (Object api : new ArrayList<>((Collection<?>)list)) unique.put(providerId(api),api); }
        return new ArrayList<>(unique.values());
    }
    private static String providerId(Object api) throws Exception {
        return property(api,"name") + "::" + property(api,"sourcePlugin");
    }
    private static Object provider(String name) throws Exception {
        Object match = null;
        for (Object api : providers()) {
            if (name.equals(providerId(api))) return api;
            if (name.equals(property(api,"name"))) {
                if (match != null) throw new IllegalArgumentException("Ambiguous provider: use its id");
                match = api;
            }
        }
        if (match != null) return match;
        throw new IllegalArgumentException("Provider not loaded: " + name);
    }
    private static JSONObject summary(Object api) throws Exception {
        JSONObject item = new JSONObject().put("id",providerId(api)).put("sourcePlugin",property(api,"sourcePlugin"));
        for (String field : new String[]{"name","lang","mainUrl","hasMainPage","hasQuickSearch"})
            item.put(field, property(api,field));
        item.put("supportedTypes", new JSONArray(json(property(api,"supportedTypes"))));
        item.put("mainPage", new JSONArray(json(property(api,"mainPage"))));
        return item;
    }
    private static Object dispatch(String verb, String path, JSONObject body) throws Exception {
        if (verb.equals("GET") && path.equals("/health"))
            return new JSONObject().put("status","ready").put("providers",providers().size()).put("runtime","Android CloudStream");
        if (verb.equals("GET") && path.equals("/providers")) {
            JSONArray items = new JSONArray();
            for (Object api : providers()) items.put(summary(api));
            return items;
        }
        if (!verb.equals("POST")) throw new IllegalArgumentException("Unknown endpoint");
        if (path.equals("/repository")) synchronized(mutations) {
            String url = body.getString("url");
            Object manager = singleton("com.lagradost.cloudstream3.plugins.RepositoryManager");
            Object repo = suspend(manager,"parseRepository",url);
            if (repo == null) throw new IllegalArgumentException("Invalid repository");
            Object data = cls("com.lagradost.cloudstream3.ui.settings.extensions.RepositoryData")
                .getConstructor(String.class,String.class).newInstance(property(repo,"name"),url);
            suspend(manager,"addRepository",data);
            List<?> plugins = (List<?>)suspend(manager,"getRepoPlugins",data);
            if (plugins == null) throw new IllegalArgumentException("Plugin list unavailable");
            JSONArray installed = new JSONArray();
            Object loader = singleton("com.lagradost.cloudstream3.plugins.PluginManager");
            for (Object wrapper : plugins) {
                Object plugin = property(wrapper,"plugin");
                JSONObject item = new JSONObject().put("internalName",property(plugin,"internalName"));
                try {
                    Object ok = suspend(loader,"downloadPlugin",activity,property(plugin,"url"),
                        property(plugin,"fileHash"),property(plugin,"internalName"),url,true);
                    item.put("loaded",ok);
                    if (!Boolean.TRUE.equals(ok)) item.put("error","CloudStream loader rejected the plugin; see Android logs");
                } catch (Exception e) { item.put("loaded",false).put("error",root(e).toString()); }
                installed.put(item);
            }
            return new JSONObject().put("repository",property(repo,"name")).put("plugins",installed);
        }
        Object api = provider(body.getString("provider"));
        switch (path) {
            case "/provider/home": {
                List<?> pages = (List<?>)property(api,"mainPage");
                int section = body.optInt("section",0);
                if (section < 0 || section >= pages.size()) throw new IllegalArgumentException("Invalid section");
                Object page = pages.get(section);
                Object request = cls("com.lagradost.cloudstream3.MainPageRequest")
                    .getConstructor(String.class,String.class,boolean.class)
                    .newInstance(property(page,"name"),property(page,"data"),property(page,"horizontalImages"));
                return suspend(api,"getMainPage",body.optInt("page",1),request);
            }
            case "/provider/search": return suspend(api,"search",body.getString("query"),body.optInt("page",1));
            case "/provider/load": return suspend(api,"load",body.getString("url"));
            case "/provider/resolve": {
                List<Object> links = Collections.synchronizedList(new ArrayList<>());
                List<Object> subtitles = Collections.synchronizedList(new ArrayList<>());
                Object ok = suspend(api,"loadLinks",body.getString("data"),false,function(subtitles),function(links));
                JSONArray streams = new JSONArray();
                for (Object link : links) {
                    JSONObject item = new JSONObject(json(link));
                    item.put("headers",new JSONObject(json(call(link,"getAllHeaders"))));
                    streams.put(item);
                }
                return new JSONObject().put("success",ok).put("streams",streams).put("subtitles",new JSONArray(json(subtitles)));
            }
            default: throw new IllegalArgumentException("Unknown endpoint");
        }
    }
    private static Throwable root(Throwable e) {
        while (e instanceof InvocationTargetException && e.getCause() != null) e = e.getCause();
        return e;
    }
    private static String line(InputStream input) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        for (int ch; (ch=input.read()) != -1;) {
            if (ch=='\n') break;
            if (ch!='\r') out.write(ch);
            if (out.size()>8192) throw new IOException("Header too long");
        }
        return out.toString("UTF-8");
    }
    private static void handle(Socket socket) {
        try (Socket client = socket) {
            client.setSoTimeout(10000);
            InputStream input = new BufferedInputStream(client.getInputStream());
            String[] first = line(input).split(" ");
            if (first.length != 3) return;
            int length = 0, count = 0;
            for (String header; !(header=line(input)).isEmpty();) {
                if (++count > 64) throw new IOException("Too many headers");
                if (header.toLowerCase(Locale.ROOT).startsWith("content-length:")) length=Integer.parseInt(header.substring(15).trim());
                if (header.toLowerCase(Locale.ROOT).startsWith("transfer-encoding:")) throw new IOException("Chunked input unsupported");
            }
            if (length<0 || length>2*1024*1024) throw new IOException("Body too large");
            byte[] bytes = new byte[length];
            new DataInputStream(input).readFully(bytes);
            if (first[0].equals("POST") && first[1].equals("/media")) {
                relay(client,new JSONObject(new String(bytes,StandardCharsets.UTF_8)));
                return;
            }
            int status = 200; String payload;
            try {
                JSONObject body = length==0 ? new JSONObject() : new JSONObject(new String(bytes,StandardCharsets.UTF_8));
                payload=json(dispatch(first[0],first[1].split("\\?",2)[0],body));
            } catch (Throwable e) {
                Throwable cause=root(e);
                status=cause instanceof IllegalArgumentException ? 400 : 502;
                payload=new JSONObject().put("error",cause.toString()).toString();
                Log.e("CS3Server","Request failed",cause);
            }
            byte[] response=payload.getBytes(StandardCharsets.UTF_8);
            OutputStream out=client.getOutputStream();
            out.write(("HTTP/1.1 "+status+" Result\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: "+response.length+"\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
            out.write(response); out.flush();
        } catch (Exception e) { Log.w("CS3Server","HTTP connection closed",e); }
    }
    private static void relay(Socket client, JSONObject request) throws Exception {
        URL target = new URL(request.getString("url"));
        if (!target.getProtocol().equals("https") && !target.getProtocol().equals("http")) throw new IllegalArgumentException("HTTP media only");
        HttpURLConnection connection = (HttpURLConnection)target.openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setInstanceFollowRedirects(false);
        JSONObject headers=request.optJSONObject("headers");
        if (headers!=null) for (Iterator<String> names=headers.keys();names.hasNext();) {
            String name=names.next();
            if (name.equalsIgnoreCase("Host") || name.equalsIgnoreCase("Connection") || name.equalsIgnoreCase("Content-Length")) continue;
            connection.setRequestProperty(name,headers.getString(name));
        }
        connection.setRequestProperty("Accept-Encoding","identity");
        int status=connection.getResponseCode();
        OutputStream output=client.getOutputStream();
        StringBuilder response=new StringBuilder("HTTP/1.1 ").append(status).append(" Result\r\nConnection: close\r\n");
        for (String name : new String[]{"Content-Type","Content-Length","Content-Range","Accept-Ranges","Location"}) {
            String value=connection.getHeaderField(name);
            if (value!=null) response.append(name).append(": ").append(value).append("\r\n");
        }
        output.write(response.append("\r\n").toString().getBytes(StandardCharsets.US_ASCII));
        try (InputStream upstream=status>=400 ? connection.getErrorStream() : connection.getInputStream()) {
            if (upstream!=null) { byte[] buffer=new byte[65536]; for (int n;(n=upstream.read(buffer))!=-1;) output.write(buffer,0,n); }
            output.flush();
        } finally { connection.disconnect(); }
    }
}
