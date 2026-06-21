package com.plantoplate.controller;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.web.servlet.MockMvc;

import static org.hamcrest.Matchers.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * Web slice test verifying template resolution for root path (/).
 * Ensures incoming traffic resolves to the base structural HTML layout frame
 * without Thymeleaf parsing exceptions.
 */
@WebMvcTest(HomeController.class)
public class HomeControllerWebMvcTest {

    @Autowired
    private MockMvc mockMvc;

    /**
     * Verifies that a request to the root path returns the index template
     * with expected HTTP status and content type headers.
     */
    @Test
    public void testRootPathResolution() throws Exception {
        mockMvc.perform(get("/"))
            .andExpect(status().isOk())
            .andExpect(content().contentType("text/html;charset=UTF-8"))
            .andExpect(view().name("index"));
    }

    /**
     * Verifies that the response includes expected HTML elements from the application.
     * Note: Layout framework imports (HTMX, Tailwind) are in fragments/layout.html
     * which is loaded via Thymeleaf includes at parent level.
     */
    @Test
    public void testApplicationContent() throws Exception {
        mockMvc.perform(get("/"))
            .andExpect(status().isOk())
            .andExpect(content().string(containsString("<!DOCTYPE html>")))
            .andExpect(content().string(containsString("PlanToPlate")))
            .andExpect(content().string(containsString("Welcome to PlanToPlate")));
    }

    /**
     * Verifies that Thymeleaf successfully renders without parsing exceptions.
     * Tests that the application can serve content with proper HTML structure.
     */
    @Test
    public void testThymeleafRendering() throws Exception {
        mockMvc.perform(get("/"))
            .andExpect(status().isOk())
            .andExpect(content().contentType("text/html;charset=UTF-8"));
    }

}
