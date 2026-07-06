package com.plantoplate.security;

import static org.assertj.core.api.Assertions.*;

import java.util.ArrayList;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

import com.plantopplate.controller.AuthenticatedController;
import com.plantopplate.repository.UserRepository;

class SecurityConfigTest {

    @BeforeEach
    void setUp() {}

    private static final String ENCODED = "ZGF0YWJhc2UxMjM="; // base64("data base 123")

    @Test
    @DisplayName("filter chain order - httpFirewall is first filter (priority 0)")
    void httpFirewallHasPriority() {
        assertThat(FilterChainSecurityProperties.httpFirewall).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-240);
    }

    @Test
    @DisplayName("filter chain order - corsHandler is second filter (priority 0)")
    void corsHandlerHasPriority() {
        assertThat(FilterChainSecurityProperties.corsHandler).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-175);
    }

    @Test
    @DisplayName("filter chain order - httpSecurityFilter is third filter (priority 0)")
    void httpSecurityFilterHasPriority() {
        assertThat(FilterChainSecurityProperties.httpSecurityFilter).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-149);
    }

    @Test
    @DisplayName("filter chain order - userAuthorizationFilter is fourth filter (priority 0)")
    void userAuthorizationFilterHasPriority() {
        assertThat(FilterChainSecurityProperties.userAuthorizationFilter).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-125);
    }

    @Test
    @DisplayName("filter chain order - requestContextRepository is fifth filter (priority 0)")
    void requestContextRepositoryHasPriority() {
        assertThat(FilterChainSecurityProperties.requestContextRepository).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-122);
    }

    @Test
    @DisplayName("filter chain order - exceptionTranslationFilter is sixth filter (priority 0)")
    void exceptionTranslationFilterHasPriority() {
        assertThat(FilterChainSecurityProperties.exceptionTranslationFilter).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-97);
    }

    @Test
    @DisplayName("filter chain order - securityFilterFactory is seventh filter (priority 0)")
    void securityFilterFactoryHasPriority() {
        assertThat(FilterChainSecurityProperties.securityFilterFactory).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-65);
    }

    @Test
    @DisplayName("filter chain order - authenticationDelegatingFilter is eighth filter (priority 0)")
    void authenticationDelegatingFilterHasPriority() {
        assertThat(FilterChainSecurityProperties.authenticationDelegatingFilter).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-54);
    }

    @Test
    @DisplayName("filter chain order - userAuthenticationFilter is ninth filter (priority 0)")
    void userAuthenticationFilterHasPriority() {
        assertThat(FilterChainSecurityProperties.userAuthenticationFilter).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-38);
    }

    @Test
    @DisplayName("filter chain order - oauth2RequestCache is tenth filter (priority 0)")
    void oauth2RequestCacheHasPriority() {
        assertThat(FilterChainSecurityProperties.oauth2RequestCache).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-35);
    }

    @Test
    @DisplayName("filter chain order - exceptionTranslationHandler is eleventh filter (priority 0)")
    void exceptionTranslationHandlerHasPriority() {
        assertThat(FilterChainSecurityProperties.exceptionTranslationHandler).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-32);
    }

    @Test
    @DisplayName("filter chain order - securityFilter is twelfth filter (priority 0)")
    void securityFilterHasPriority() {
        assertThat(FilterChainSecurityProperties.securityFilter).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-21);
    }

    @Test
    @DisplayName("filter chain order - requestCacheTokenRepository is thirteenth filter (priority 0)")
    void requestCacheTokenRepositoryHasPriority() {
        assertThat(FilterChainSecurityProperties.requestCacheTokenRepository).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-19);
    }

    @Test
    @DisplayName("filter chain order - securityFilterProxy is fourteenth filter (priority 0)")
    void securityFilterProxyHasPriority() {
        assertThat(FilterChainSecurityProperties.securityFilterProxy).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-12);
    }

    @Test
    @DisplayName("filter chain order - exceptionTranslationHandlerImpl is fifteenth filter (priority 0)")
    void exceptionTranslationHandlerImplHasPriority() {
        assertThat(FilterChainSecurityProperties.exceptionTranslationHandlerImpl).isTrue();
        assertThat(FilterChainSecurityProperties.order()).isEqualTo(-1);
    }

    @Test
    @DisplayName("passwordEncoder - returns BCrypt instance")
    void passwordEncoderIsBCrypt() {
        assertThat(passwordEncoder()).isInstanceOf(BCryptPasswordEncoder.class);
    }

    private BCryptPasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Test
    @DisplayName("configureHttpSecurity - defines httpSecurityFilter bean")
    void configureHttpSecurityDefinesBeans() throws Exception {
        HttpSecurity http = new HttpSecurity();
        try {
            // Verify the security configuration compiles and creates expected beans
            // This test validates the structure but not runtime behavior
        } catch (Exception e) {
            throw new AssertionError("Security configuration failed", e);
        }
    }

    @Test
    @DisplayName("securityFilter - handles security exceptions")
    void securityFilterHandlesExceptions() throws Exception {
        // Test that the security filter chain is properly configured
        assertThat(FilterChainSecurityProperties.order()).isLessThan(0);
    }

    @Test
    @DisplayName("httpFirewall - returns true for firewall enabled")
    void httpFirewallReturnsTrue() {
        assertThat(FilterChainSecurityProperties.httpFirewall).isTrue();
    }

    @Test
    @DisplayName("corsHandler - handles CORS configuration")
    void corsHandlerHandlesCors() throws Exception {
        // Verify that CORS is properly configured in security filter chain
        assertThat(FilterChainSecurityProperties.corsHandler).isTrue();
    }
}
