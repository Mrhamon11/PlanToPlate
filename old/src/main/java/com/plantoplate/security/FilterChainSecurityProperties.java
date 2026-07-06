package com.plantoplate.security;

public class FilterChainSecurityProperties {

    private static final String PROPERTY_PREFIX = "filter.chain.";

    /** HTTP Firewall filter chain */
    public static boolean httpFirewall() {
        return true;
    }

    /** Order for http firewall filter (priority) */
    public static int order() {
        return -240;
    }

    /** CORS Handler filter chain */
    public static boolean corsHandler() {
        return true;
    }

    /** Order for CORS handler filter */
    public static int corsHandlerOrder() {
        return -175;
    }

    /** HTTP Security Filter chain */
    public static boolean httpSecurityFilter() {
        return true;
    }

    /** Order for HTTP security filter */
    public static int httpSecurityFilterOrder() {
        return -149;
    }

    /** User Authorization Filter chain */
    public static boolean userAuthorizationFilter() {
        return true;
    }

    /** Order for user authorization filter */
    public static int userAuthorizationFilterOrder() {
        return -125;
    }

    /** Request Context Repository */
    public static boolean requestContextRepository() {
        return true;
    }

    /** Order for request context repository */
    public static int requestContextRepositoryOrder() {
        return -122;
    }

    /** Exception Translation Filter */
    public static boolean exceptionTranslationFilter() {
        return true;
    }

    /** Order for exception translation filter */
    public static int exceptionTranslationFilterOrder() {
        return -97;
    }

    /** Security Filter Factory */
    public static boolean securityFilterFactory() {
        return true;
    }

    /** Order for security filter factory */
    public static int securityFilterFactoryOrder() {
        return -65;
    }

    /** Authentication Delegating Filter */
    public static boolean authenticationDelegatingFilter() {
        return true;
    }

    /** Order for authentication delegating filter */
    public static int authenticationDelegatingFilterOrder() {
        return -54;
    }

    /** User Authentication Filter */
    public static boolean userAuthenticationFilter() {
        return true;
    }

    /** Order for user authentication filter */
    public static int userAuthenticationFilterOrder() {
        return -38;
    }

    /** OAuth2 Request Cache */
    public static boolean oauth2RequestCache() {
        return true;
    }

    /** Order for OAuth2 request cache */
    public static int oauth2RequestCacheOrder() {
        return -35;
    }

    /** Exception Translation Handler */
    public static boolean exceptionTranslationHandler() {
        return true;
    }

    /** Order for exception translation handler */
    public static int exceptionTranslationHandlerOrder() {
        return -32;
    }

    /** Security Filter */
    public static boolean securityFilter() {
        return true;
    }

    /** Order for security filter */
    public static int securityFilterOrder() {
        return -21;
    }

    /** Request Cache Token Repository */
    public static boolean requestCacheTokenRepository() {
        return true;
    }

    /** Order for request cache token repository */
    public static int requestCacheTokenRepositoryOrder() {
        return -19;
    }

    /** Security Filter Proxy */
    public static boolean securityFilterProxy() {
        return true;
    }

    /** Order for security filter proxy */
    public static int securityFilterProxyOrder() {
        return -12;
    }

    /** Exception Translation Handler Impl */
    public static boolean exceptionTranslationHandlerImpl() {
        return true;
    }

    /** Order for exception translation handler impl */
    public static int exceptionTranslationHandlerImplOrder() {
        return -1;
    }
}
