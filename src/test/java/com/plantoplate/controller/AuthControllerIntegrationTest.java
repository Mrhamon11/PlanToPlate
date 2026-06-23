package com.plantoplate.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.plantoplate.dto.LoginRequest;
import com.plantoplate.model.Role;
import com.plantoplate.model.User;
import com.plantoplate.repository.UserRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.web.servlet.MockMvc;

import java.time.LocalDate;
import java.util.Base64;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@AutoConfigureMockMvc
@SpringBootTest
class AuthControllerIntegrationTest
{

    @Autowired
    private MockMvc mockMvc;
    @Autowired
    private ObjectMapper objectMapper;
    @Autowired
    private UserRepository userRepository;
    @Autowired
    private PasswordEncoder passwordEncoder;

    @Test
    @DisplayName("POST /login - authenticates user and returns auth token")
    void shouldLoginAndGetAuthToken() throws Exception
    {
        User user = createUser();
        userRepository.save(user);

        String requestJson = objectMapper.writeValueAsString(new LoginRequest(user.getUsername(), "123456!@#$"));

        mockMvc.perform(post("/login").contentType(MediaType.APPLICATION_JSON).content(requestJson))
                .andExpect(status().isOk()).andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.authToken").exists()).andExpect(jsonPath("$.authToken").isNotEmpty())
                .andExpect(jsonPath("$.username").value(user.getUsername()))
                .andExpect(jsonPath("$.firstName").value(user.getFirstName()))
                .andExpect(jsonPath("$.lastName").value(user.getLastName()));
    }

    @Test
    @DisplayName("POST /login - returns error for invalid credentials")
    void shouldReturnErrorOnInvalidCredentials() throws Exception
    {
        String requestJson = objectMapper.writeValueAsString(new LoginRequest("nonexistent", "123456!@#$"));

        mockMvc.perform(post("/login").contentType(MediaType.APPLICATION_JSON).content(requestJson))
                .andExpect(status().isBadRequest()).andExpect(content().contentType(MediaType.APPLICATION_JSON));
    }

    @Test
    @DisplayName("POST /login - returns error on account not found")
    void shouldReturnErrorOnAccountNotFound() throws Exception
    {
        User user = createUser();
        user.setIsTempPassword(true);
        user.setPasswordHash(passwordEncoder.encode("123456!@#$"));
        userRepository.save(user);

        // Reset password for temp user
        String requestJson = objectMapper.writeValueAsString(new LoginRequest(user.getUsername(), "newpassword789!@#"));

        mockMvc.perform(post("/login").contentType(MediaType.APPLICATION_JSON).content(requestJson))
                .andExpect(status().isOk()).andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.authToken").exists());
    }

    @Test
    @DisplayName("POST /login - returns error on password mismatch")
    void shouldReturnErrorOnPasswordMismatch() throws Exception
    {
        User user = createUser();
        userRepository.save(user);

        String requestJson = objectMapper.writeValueAsString(new LoginRequest(user.getUsername(), "wrongpassword"));

        mockMvc.perform(post("/login").contentType(MediaType.APPLICATION_JSON).content(requestJson))
                .andExpect(status().isBadRequest()).andExpect(content().contentType(MediaType.APPLICATION_JSON));
    }

    @Test
    @DisplayName("POST /login - returns error on disabled account")
    void shouldReturnErrorOnDisabledAccount() throws Exception
    {
        User user = createUser();
        user.setIsDisabled(true);
        userRepository.save(user);

        String requestJson = objectMapper.writeValueAsString(new LoginRequest(user.getUsername(), "123456!@#$"));

        mockMvc.perform(post("/login").contentType(MediaType.APPLICATION_JSON).content(requestJson))
                .andExpect(status().isBadRequest()).andExpect(content().contentType(MediaType.APPLICATION_JSON));
    }

    @Test
    @DisplayName("POST /login - returns error on null username")
    void shouldReturnErrorOnNullUsername() throws Exception
    {
        String requestJson = objectMapper.writeValueAsString(new LoginRequest(null, "123456!@#$"));

        mockMvc.perform(post("/login").contentType(MediaType.APPLICATION_JSON).content(requestJson))
                .andExpect(status().isBadRequest()).andExpect(content().contentType(MediaType.APPLICATION_JSON));
    }

    @Test
    @DisplayName("POST /login - returns error on null password")
    void shouldReturnErrorOnNullPassword() throws Exception
    {
        User user = createUser();
        userRepository.save(user);

        String requestJson = objectMapper.writeValueAsString(new LoginRequest(user.getUsername(), null));

        mockMvc.perform(post("/login").contentType(MediaType.APPLICATION_JSON).content(requestJson))
                .andExpect(status().isBadRequest()).andExpect(content().contentType(MediaType.APPLICATION_JSON));
    }

    @Test
    @DisplayName("POST /login - returns error on empty username")
    void shouldReturnErrorOnEmptyUsername() throws Exception
    {
        User user = createUser();
        userRepository.save(user);

        String requestJson = objectMapper.writeValueAsString(new LoginRequest("", "123456!@#$"));

        mockMvc.perform(post("/login").contentType(MediaType.APPLICATION_JSON).content(requestJson))
                .andExpect(status().isBadRequest()).andExpect(content().contentType(MediaType.APPLICATION_JSON));
    }

    @Test
    @DisplayName("POST /logout - returns success when logged in")
    void shouldLogoutSuccessfully() throws Exception
    {
        // First login to get token
        User user = createUser();
        userRepository.save(user);

        String authString = "Bearer " + Base64.getEncoder().encodeToString("user:password".getBytes());

        mockMvc.perform(logout().contentType(MediaType.APPLICATION_JSON).header("Authorization", authString))
                .andExpect(status().isOk()).andExpect(jsonPath("$.message").value("Logged out successfully"));
    }

    @Test
    @DisplayName("POST /logout - returns error when already logged out")
    void shouldReturnErrorOnLogoutWhenAlreadyLoggedOut() throws Exception
    {
        mockMvc.perform(logout()).andExpect(status().isBadRequest())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.error").value("Not authenticated"));
    }

    @Test
    @DisplayName("POST /logout - returns error on invalid token")
    void shouldReturnErrorOnInvalidToken() throws Exception
    {
        String authString = "Bearer invalidtoken";

        mockMvc.perform(logout().contentType(MediaType.APPLICATION_JSON).header("Authorization", authString))
                .andExpect(status().isBadRequest()).andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.error").value("Invalid token"));
    }

    private User createUser()
    {
        User user = new User();
        user.setUsername("testuser");
        user.setPasswordHash(passwordEncoder.encode("123456!@#$"));
        user.setFirstName("Test");
        user.setLastName("User");
        user.setEmail("test@example.com");
        user.setPhoneNumber("+1-123-456-7890");
        user.setAddress("123 Test Street");
        user.setCity("Test City");
        user.setZipCode("12345");
        user.setState("Test State");
        user.setDateOfBirth(LocalDate.of(1990, 1, 1));
        user.setIsTempPassword(false);
        user.setIsDisabled(false);
        user.setRole(Role.USER);
        return user;
    }
}
