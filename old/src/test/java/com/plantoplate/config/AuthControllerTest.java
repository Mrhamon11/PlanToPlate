package com.plantoplate.config;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.security.test.context.support.WithMockUser;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(AuthController.class)
class AuthControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    @WithMockUser(username = "user", roles = {"USER"})
    void testLogout() throws Exception {
        mockMvc.perform(get("/logout"))
            .andExpect(status().is3xxRedirection())
            .andExpect(redirectedUrl("http://localhost/login"));
    }

    @Test
    @WithMockUser(username = "user", roles = {"USER"})
    void testLoginSuccess() throws Exception {
        mockMvc.perform(get("/login"))
            .andExpect(status().is3xxRedirection())
            .andExpect(redirectedUrl("http://localhost/home"));
    }

    @Test
    @WithMockUser(username = "user", roles = {"USER"})
    void testRegister() throws Exception {
        mockMvc.perform(post("/register")
                .param("username", "newuser")
                .param("password", "securepass123"))
            .andExpect(status().is3xxRedirection())
            .andExpect(redirectedUrl("http://localhost/home"));
    }

    @Test
    void testLoginFailure() throws Exception {
        mockMvc.perform(get("/login")
                .param("username", "invaliduser"))
            .andExpect(status().isOk());
    }

    @Test
    void testRegisterFailure() throws Exception {
        mockMvc.perform(post("/register")
                .param("username", ""))
            .andExpect(status().is4xxClientError());
    }
}
